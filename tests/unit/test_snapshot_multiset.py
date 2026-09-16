"""Snapshots are multisets: identical value-rows must match in count.

Minified JavaScript puts many functions on one line, so distinct functions
collapse to identical (path, name, kind, line, signature) rows: Django's
vendored select2 holds eleven ``function e(e,t,n)`` on line 2. A set-based
snapshot would call an index holding one such row and a rebuild holding
eleven "converged". Counting them keeps ``cidx check`` and the convergence
suite honest about "identical to a cold rebuild".
"""

from __future__ import annotations

from pathlib import Path

from cidx.core import incremental, indexer
from cidx.core.store import Store

MINIFIED = b"function e(){return 1}function e(){return 2}\n"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "vendor.min.js").write_bytes(MINIFIED)
    return repo


def test_snapshot_counts_identical_rows(tmp_path: Path) -> None:
    with Store.open(tmp_path / "index.db") as store:
        indexer.index_repository(_repo(tmp_path), store)
        symbols = store.snapshot()["symbols"]
        assert store.stats()["symbols"] == 2, "premise: two `function e` symbols"
        assert sum(symbols.values()) == 2
        assert max(symbols.values()) == 2, "the two rows are value-identical"


def test_check_drift_reports_a_missing_duplicate(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with Store.open(tmp_path / "index.db") as store:
        indexer.index_repository(repo, store)
        assert incremental.check_drift(repo, store) == []
        connection = store.connection
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM symbols WHERE id = (SELECT MIN(id) FROM symbols)"
        )
        connection.execute("COMMIT")
        drifts = incremental.check_drift(repo, store)
    assert [drift.table for drift in drifts] == ["symbols"], (
        "one of two identical rows vanished and the check must notice"
    )
    assert len(drifts[0].missing) == 1 and drifts[0].extra == ()
