"""Tests for the incremental engine and the drift checker."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from cidx.core import incremental, indexer
from cidx.core.store import Store

PY_ONE = b"def one():\n    return 1\n"
PY_TWO = b"def two():\n    return 2\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    with Store.open(tmp_path / "cache" / "index.db") as opened:
        yield opened


class TestRefreshPath:
    def test_new_file_is_indexed(self, repo: Path, store: Store) -> None:
        (repo / "a.py").write_bytes(PY_ONE)
        assert incremental.refresh_path(store, repo, "a.py") == "updated"
        assert [r.path for r in store.lookup_exact("one")] == ["a.py"]

    def test_unchanged_content_is_free(self, repo: Path, store: Store) -> None:
        (repo / "a.py").write_bytes(PY_ONE)
        incremental.refresh_path(store, repo, "a.py")
        assert incremental.refresh_path(store, repo, "a.py") == "unchanged"

    def test_touched_but_identical_content_is_unchanged(
        self, repo: Path, store: Store
    ) -> None:
        (repo / "a.py").write_bytes(PY_ONE)
        incremental.refresh_path(store, repo, "a.py")
        (repo / "a.py").write_bytes(PY_ONE)  # new mtime, same bytes
        assert incremental.refresh_path(store, repo, "a.py") == "unchanged"

    def test_modified_file_swaps_rows(self, repo: Path, store: Store) -> None:
        (repo / "a.py").write_bytes(PY_ONE)
        incremental.refresh_path(store, repo, "a.py")
        (repo / "a.py").write_bytes(PY_TWO)
        assert incremental.refresh_path(store, repo, "a.py") == "updated"
        assert store.lookup_exact("one") == []
        assert [r.path for r in store.lookup_exact("two")] == ["a.py"]

    def test_deleted_file_removes_rows(self, repo: Path, store: Store) -> None:
        (repo / "a.py").write_bytes(PY_ONE)
        incremental.refresh_path(store, repo, "a.py")
        (repo / "a.py").unlink()
        assert incremental.refresh_path(store, repo, "a.py") == "removed"
        assert store.stats()["files"] == 0

    def test_never_seen_missing_path_is_absent(self, repo: Path, store: Store) -> None:
        assert incremental.refresh_path(store, repo, "ghost.py") == "absent"

    def test_rename_converges_via_both_paths(
        self, repo: Path, store: Store, tmp_path: Path
    ) -> None:
        (repo / "old.py").write_bytes(PY_ONE)
        incremental.refresh_path(store, repo, "old.py")
        (repo / "old.py").rename(repo / "new.py")
        incremental.refresh_path(store, repo, "old.py")
        incremental.refresh_path(store, repo, "new.py")
        with Store.open(tmp_path / "cold" / "index.db") as cold:
            indexer.index_repository(repo, cold)
            assert store.snapshot() == cold.snapshot()

    def test_file_growing_past_cap_is_removed(self, repo: Path, store: Store) -> None:
        (repo / "a.py").write_bytes(PY_ONE)
        incremental.refresh_path(store, repo, "a.py", max_file_bytes=1_000)
        (repo / "a.py").write_bytes(b"# " + b"x" * 2_000)
        outcome = incremental.refresh_path(store, repo, "a.py", max_file_bytes=1_000)
        assert outcome == "removed"
        assert store.stats()["files"] == 0

    @pytest.mark.skipif(
        os.name != "nt",
        reason="backslash is a separator only on Windows; on POSIX it is a"
        " legal filename character and must not be rewritten",
    )
    def test_windows_style_relative_path_is_normalized(
        self, repo: Path, store: Store
    ) -> None:
        (repo / "pkg").mkdir()
        (repo / "pkg" / "a.py").write_bytes(PY_ONE)
        assert incremental.refresh_path(store, repo, "pkg\\a.py") == "updated"
        assert store.file_record("pkg/a.py") is not None

    def test_unsupported_extension_removes_prior_rows(
        self, repo: Path, store: Store
    ) -> None:
        (repo / "a.py").write_bytes(PY_ONE)
        incremental.refresh_path(store, repo, "a.py")
        (repo / "a.py").rename(repo / "a.txt")
        assert incremental.refresh_path(store, repo, "a.py") == "removed"
        assert incremental.refresh_path(store, repo, "a.txt") == "absent"


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
class TestIgnoreParityWithDiscovery:
    """Regression: refresh_path must never index what discovery excludes."""

    def test_gitignored_path_is_refused_by_the_engine(
        self, repo: Path, store: Store
    ) -> None:
        subprocess.run(
            ["git", "init", "--quiet", str(repo)], check=True, capture_output=True
        )
        (repo / ".gitignore").write_text("generated/\n", encoding="utf-8")
        (repo / "generated").mkdir()
        (repo / "generated" / "gen.py").write_bytes(PY_ONE)
        assert incremental.refresh_path(store, repo, "generated/gen.py") == "absent"
        assert store.stats()["files"] == 0
        assert incremental.check_drift(repo, store) == []

    def test_newly_ignored_indexed_file_is_removed_on_refresh(
        self, repo: Path, store: Store
    ) -> None:
        subprocess.run(
            ["git", "init", "--quiet", str(repo)], check=True, capture_output=True
        )
        (repo / "a.py").write_bytes(PY_ONE)
        incremental.refresh_path(store, repo, "a.py")
        (repo / ".gitignore").write_text("a.py\n", encoding="utf-8")
        assert incremental.refresh_path(store, repo, "a.py") == "removed"
        assert incremental.check_drift(repo, store) == []

    def test_junk_directory_paths_are_refused_without_git(
        self, repo: Path, store: Store
    ) -> None:
        junk = repo / "node_modules"
        junk.mkdir()
        (junk / "dep.py").write_bytes(PY_ONE)
        assert incremental.refresh_path(store, repo, "node_modules/dep.py") == "absent"
        assert store.stats()["files"] == 0


class TestCheckDrift:
    def test_fresh_cold_index_has_no_drift(self, repo: Path, store: Store) -> None:
        (repo / "a.py").write_bytes(PY_ONE)
        indexer.index_repository(repo, store)
        assert incremental.check_drift(repo, store) == []

    def test_incremental_history_has_no_drift(self, repo: Path, store: Store) -> None:
        (repo / "a.py").write_bytes(PY_ONE)
        incremental.refresh_path(store, repo, "a.py")
        (repo / "a.py").write_bytes(PY_TWO)
        incremental.refresh_path(store, repo, "a.py")
        (repo / "b.ts").write_bytes(b"export const x = 1;\n")
        incremental.refresh_path(store, repo, "b.ts")
        assert incremental.check_drift(repo, store) == []

    def test_manual_corruption_is_reported_exactly(
        self, repo: Path, store: Store
    ) -> None:
        (repo / "a.py").write_bytes(PY_ONE)
        indexer.index_repository(repo, store)
        store._connection.execute("DELETE FROM symbols")
        drifts = incremental.check_drift(repo, store)
        assert [d.table for d in drifts] == ["symbols"]
        (row,) = drifts[0].missing
        assert row[0] == "a.py"
        assert row[2] == "one"  # qualified_name of the vanished symbol
        assert drifts[0].extra == ()

    def test_stale_extra_file_is_reported(self, repo: Path, store: Store) -> None:
        (repo / "a.py").write_bytes(PY_ONE)
        indexer.index_repository(repo, store)
        (repo / "a.py").unlink()  # index now stale on purpose
        drifts = incremental.check_drift(repo, store)
        tables = {d.table for d in drifts}
        assert "files" in tables
        files_drift = next(d for d in drifts if d.table == "files")
        assert files_drift.extra[0][0] == "a.py"
        assert files_drift.missing == ()
