"""Regression tests for the batched reconciliation sweep (ADR-015).

``cidx serve`` builds its index through the watcher's first sweep. Before
ADR-015 that sweep resolved the WHOLE index once per file and spawned one
``git check-ignore`` per file, making a cold start O(n^2): a 3,000-file
repository did not finish within 400 seconds.

These tests assert the *work contract* -- how many times the expensive global
operations run -- rather than wall-clock times, so they are deterministic and
cannot flake on a slow or loaded CI machine.
"""

from __future__ import annotations

from cidx.core import incremental, indexer
from cidx.core.store import Store
from cidx.core.watcher import Watcher


def _repo(tmp_path, count=12):
    repo = tmp_path / "repo"
    repo.mkdir()
    for i in range(count):
        (repo / f"mod{i}.py").write_text(f"def fn{i}():\n    return {i}\n")
    return repo


def _count_resolves(monkeypatch):
    calls = {"n": 0}
    original = Store.resolve_references

    def counting(self):
        calls["n"] += 1
        return original(self)

    monkeypatch.setattr(Store, "resolve_references", counting)
    return calls


def test_sweep_resolves_once_not_once_per_file(tmp_path, monkeypatch):
    """The O(n^2) guard: whole-index resolution is batched to the sweep's end."""
    repo = _repo(tmp_path, count=12)
    calls = _count_resolves(monkeypatch)

    watcher = Watcher(repo, tmp_path / "index.db")
    with Store.open(tmp_path / "index.db") as store:
        watcher._sweep(store)
        indexed = store.stats()["files"]

    assert indexed == 12, "the sweep must still index every discovered file"
    assert calls["n"] == 1, (
        f"sweep resolved {calls['n']} times for 12 files; resolution is a"
        " whole-index recompute and must run once per sweep, or a cold"
        " `cidx serve` start is quadratic (ADR-015)"
    )


def test_sweep_does_not_check_ignore_per_file(tmp_path, monkeypatch):
    """Discovery already applied the ignore rules; re-checking spawns git."""
    repo = _repo(tmp_path, count=12)
    calls = {"n": 0}
    original = indexer.is_ignored

    def counting(root, relative_posix):
        calls["n"] += 1
        return original(root, relative_posix)

    monkeypatch.setattr(indexer, "is_ignored", counting)

    watcher = Watcher(repo, tmp_path / "index.db")
    with Store.open(tmp_path / "index.db") as store:
        watcher._sweep(store)

    assert calls["n"] == 0, (
        f"sweep ran is_ignored {calls['n']} times; paths come from"
        " iter_source_files, which has already applied gitignore and the"
        " junk-directory skip-list, and each call spawns a subprocess"
    )


def test_sweep_resolves_even_when_stopped_early(tmp_path, monkeypatch):
    """Deferred resolution must not be lost when the sweep aborts on stop."""
    repo = _repo(tmp_path, count=12)
    calls = _count_resolves(monkeypatch)

    watcher = Watcher(repo, tmp_path / "index.db")
    watcher._stop_event.set()  # abort at the first loop check
    with Store.open(tmp_path / "index.db") as store:
        watcher._sweep(store)

    assert calls["n"] == 1, (
        "an early-exiting sweep must still resolve, or it leaves the index"
        " holding rows whose references were never resolved"
    )


def test_single_refresh_still_resolves_immediately(tmp_path, monkeypatch):
    """One edited file stays self-contained and immediately queryable."""
    repo = _repo(tmp_path, count=1)
    with Store.open(tmp_path / "index.db") as store:
        indexer.index_repository(repo, store)
        (repo / "mod0.py").write_text("def renamed():\n    return 0\n")
        calls = _count_resolves(monkeypatch)
        outcome = incremental.refresh_path(store, repo, "mod0.py")

        assert outcome == "updated"
        assert calls["n"] == 1, (
            "the watcher's per-event path must resolve on the spot; deferring"
            " is only safe inside a batch that resolves at the end"
        )


def test_sweep_converges_with_deferred_resolution(tmp_path):
    """The invariant itself: a swept index equals a cold rebuild."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def helper():\n    return 1\n")
    (repo / "b.py").write_text(
        "from a import helper\n\n\ndef use():\n    return helper()\n"
    )

    watcher = Watcher(repo, tmp_path / "index.db")
    with Store.open(tmp_path / "index.db") as store:
        watcher._sweep(store)
        assert incremental.check_drift(repo, store) == [], (
            "a watcher-built index must equal a cold rebuild, resolved"
            " reference targets included"
        )
