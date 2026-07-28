"""Integration tests for the watcher: real observer, real threads, real files.

Timing-sensitive by nature, so every assertion polls with a generous deadline
rather than sleeping fixed amounts.
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


def wait_for(predicate: Callable[[], bool], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def converged(repo: Path, db_path: Path) -> bool:
    with Store.open(db_path) as reader:
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


class TestEventPath:
    def test_new_file_becomes_queryable(
        self, repo: Path, db_path: Path, watcher: Watcher
    ) -> None:
        (repo / "fresh.py").write_bytes(b"def fresh_symbol():\n    pass\n")

        def indexed() -> bool:
            with Store.open(db_path) as reader:
                return bool(reader.lookup_exact("fresh_symbol"))

        assert wait_for(indexed)

    def test_edits_deletes_and_renames_converge(
        self, repo: Path, db_path: Path, watcher: Watcher
    ) -> None:
        (repo / "a.py").write_bytes(b"def first():\n    pass\n")
        (repo / "b.ts").write_bytes(b"export const x = () => run();\n")
        assert wait_for(lambda: converged(repo, db_path))
        (repo / "a.py").write_bytes(b"def second():\n    pass\n")
        (repo / "b.ts").rename(repo / "c.ts")
        (repo / "app.py").unlink()
        assert wait_for(lambda: converged(repo, db_path))

    def test_branch_switch_storm_converges(
        self, repo: Path, db_path: Path, watcher: Watcher
    ) -> None:
        for i in range(30):
            (repo / f"mod_{i:02d}.py").write_bytes(
                f"def before_{i}():\n    return {i}\n".encode()
            )
        assert wait_for(lambda: converged(repo, db_path), timeout=20.0)
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
        assert wait_for(lambda: converged(repo, db_path), timeout=20.0)


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

            def indexed() -> bool:
                with Store.open(db_path) as reader:
                    return bool(reader.lookup_exact("unheard"))

            assert wait_for(indexed)
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

            def public_indexed() -> bool:
                with Store.open(db_path) as reader:
                    return bool(reader.lookup_exact("visible"))

            assert wait_for(public_indexed)
            with Store.open(db_path) as reader:
                assert reader.lookup_exact("hidden") == []
                assert "secret.py" not in reader.indexed_paths()
        finally:
            instance.stop()


class TestLatency:
    def test_save_to_queryable_p95(
        self, repo: Path, db_path: Path, watcher: Watcher
    ) -> None:
        target = repo / "hot.py"
        samples: list[float] = []
        for i in range(20):
            marker = f"edit_marker_{i}"
            started = time.monotonic()
            target.write_bytes(f"def {marker}():\n    return {i}\n".encode())

            def queryable(name: str = marker) -> bool:
                with Store.open(db_path) as reader:
                    return bool(reader.lookup_exact(name))

            assert wait_for(queryable), f"edit {i} never became queryable"
            samples.append(time.monotonic() - started)
        samples.sort()
        p95 = samples[int(len(samples) * 0.95) - 1]
        print(f"\nsave-to-queryable p95: {p95 * 1000:.0f}ms over {len(samples)} edits")
        assert p95 < 2.0  # generous CI bound; the target number is reported above
