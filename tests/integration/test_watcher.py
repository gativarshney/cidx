"""Integration tests for the watcher: real observer, real threads, real files.

Timing-sensitive by nature, so every assertion polls with a generous deadline
rather than sleeping fixed amounts. Polling is deliberately gentle on the
database: each test reuses one long-lived reader connection (WAL readers see
every committed write) instead of opening a connection per poll, and the
expensive cold-rebuild comparison runs at a slow interval — CI runners are
much slower than the watcher itself.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from cidx.core import indexer
from cidx.core.store import Store
from cidx.core.watcher import Watcher

GIT = shutil.which("git")


def wait_for(
    predicate: Callable[[], bool], timeout: float = 15.0, interval: float = 0.05
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def converged(repo: Path, reader: Store) -> bool:
    live = reader.snapshot()
    # a fresh database every time: a reused one would keep stale rows and
    # make the comparison unwinnable after deletes
    with tempfile.TemporaryDirectory(prefix="cidx-cold-") as tmp:
        with Store.open(Path(tmp) / "cold.db") as cold:
            indexer.index_repository(repo, cold)
            return live == cold.snapshot()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_bytes(b"def boot():\n    return 1\n")
    return root


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "index.db"


@pytest.fixture
def watcher(repo: Path, db_path: Path) -> Iterator[Watcher]:
    instance = Watcher(
        repo,
        db_path,
        debounce_seconds=0.05,
        sweep_interval_seconds=3600.0,  # events only; sweep tests override
    )
    instance.start()
    yield instance
    instance.stop()


@pytest.fixture
def reader(db_path: Path, watcher: Watcher) -> Iterator[Store]:
    """One long-lived read connection, opened once the consumer creates the db."""
    assert wait_for(db_path.exists, timeout=10.0)
    with Store.open(db_path) as opened:
        yield opened


class TestEventPath:
    def test_new_file_becomes_queryable(self, repo: Path, reader: Store) -> None:
        (repo / "fresh.py").write_bytes(b"def fresh_symbol():\n    pass\n")
        assert wait_for(lambda: bool(reader.lookup_exact("fresh_symbol")))

    def test_edits_deletes_and_renames_converge(
        self, repo: Path, reader: Store
    ) -> None:
        (repo / "a.py").write_bytes(b"def first():\n    pass\n")
        (repo / "b.ts").write_bytes(b"export const x = () => run();\n")
        assert wait_for(lambda: converged(repo, reader), interval=0.5)
        (repo / "a.py").write_bytes(b"def second():\n    pass\n")
        (repo / "b.ts").rename(repo / "c.ts")
        (repo / "app.py").unlink()
        assert wait_for(lambda: converged(repo, reader), interval=0.5)

    def test_branch_switch_storm_converges(self, repo: Path, reader: Store) -> None:
        for i in range(30):
            (repo / f"mod_{i:02d}.py").write_bytes(
                f"def before_{i}():\n    return {i}\n".encode()
            )
        assert wait_for(lambda: converged(repo, reader), timeout=40.0, interval=0.75)
        # the storm: every file rewritten, a third deleted, new ones appear
        for i in range(30):
            target = repo / f"mod_{i:02d}.py"
            if i % 3 == 0:
                target.unlink()
            else:
                target.write_bytes(f"def after_{i}():\n    return {i}\n".encode())
        for i in range(10):
            (repo / f"new_{i:02d}.ts").write_bytes(
                f"export const item_{i} = () => go_{i}();\n".encode()
            )
        assert wait_for(lambda: converged(repo, reader), timeout=40.0, interval=0.75)


class TestReconciliationSweep:
    def test_dropped_events_are_caught_by_the_sweep(
        self, repo: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instance = Watcher(
            repo, db_path, debounce_seconds=0.05, sweep_interval_seconds=0.5
        )
        # drop every event on the floor: only the sweep can see this change
        monkeypatch.setattr(instance, "enqueue", lambda raw_path: None)
        instance.start()
        try:
            (repo / "silent.py").write_bytes(b"def unheard():\n    pass\n")
            assert wait_for(db_path.exists, timeout=10.0)
            with Store.open(db_path) as viewer:
                assert wait_for(lambda: bool(viewer.lookup_exact("unheard")))
        finally:
            instance.stop()


@pytest.mark.skipif(GIT is None, reason="git not on PATH")
class TestGitignore:
    def test_gitignored_saves_never_pollute_the_index(
        self, repo: Path, db_path: Path
    ) -> None:
        subprocess.run(
            [GIT, "init", "--quiet", str(repo)], check=True, capture_output=True
        )
        (repo / ".gitignore").write_text("secret.py\n", encoding="utf-8")
        instance = Watcher(
            repo, db_path, debounce_seconds=0.05, sweep_interval_seconds=3600.0
        )
        instance.start()
        try:
            (repo / "secret.py").write_bytes(b"def hidden():\n    pass\n")
            (repo / "public.py").write_bytes(b"def visible():\n    pass\n")
            assert wait_for(db_path.exists, timeout=10.0)
            with Store.open(db_path) as viewer:
                assert wait_for(lambda: bool(viewer.lookup_exact("visible")))
                assert viewer.lookup_exact("hidden") == []
                assert "secret.py" not in viewer.indexed_paths()
        finally:
            instance.stop()


class TestLatency:
    def test_save_to_queryable_p95(self, repo: Path, reader: Store) -> None:
        target = repo / "hot.py"
        samples: list[float] = []
        for i in range(20):
            marker = f"edit_marker_{i}"
            started = time.monotonic()
            target.write_bytes(f"def {marker}():\n    return {i}\n".encode())
            assert wait_for(lambda name=marker: bool(reader.lookup_exact(name))), (
                f"edit {i} never became queryable"
            )
            samples.append(time.monotonic() - started)
        samples.sort()
        p95 = samples[int(len(samples) * 0.95) - 1]
        print(f"\nsave-to-queryable p95: {p95 * 1000:.0f}ms over {len(samples)} edits")
        # regression guard sized for loaded CI runners; the measured target
        # (<150ms, ARCHITECTURE.md) is the printed number above
        assert p95 < 5.0
