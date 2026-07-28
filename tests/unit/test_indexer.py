"""Tests for the cold indexer: discovery, gitignore, size caps, storage."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from cidx.core import indexer
from cidx.core.store import Store

GIT = shutil.which("git")


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    with Store.open(tmp_path / "cache" / "index.db") as opened:
        yield opened


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_bytes(
        b"def main():\n    return helper()\n\n\ndef helper():\n    return 1\n"
    )
    (root / "src" / "ui.tsx").write_bytes(b"export const App = () => <Btn />;\n")
    (root / "notes.txt").write_bytes(b"not code\n")
    return root


class TestIndexRepository:
    def test_indexes_supported_files_with_relative_posix_paths(
        self, repo: Path, store: Store
    ) -> None:
        result = indexer.index_repository(repo, store)
        assert result.indexed == 2
        assert result.failed == 0
        paths = [
            row["path"]
            for row in store._connection.execute("SELECT path FROM files ORDER BY path")
        ]
        assert paths == ["src/app.py", "src/ui.tsx"]

    def test_symbols_and_refs_are_queryable_after_indexing(
        self, repo: Path, store: Store
    ) -> None:
        indexer.index_repository(repo, store)
        (match,) = store.lookup_exact("helper")
        assert match.path == "src/app.py"
        assert match.start_line == 5

    def test_size_cap_skips_generated_monsters(self, repo: Path, store: Store) -> None:
        (repo / "src" / "bundle.js").write_bytes(b"var x = 1;\n" * 200_000)
        result = indexer.index_repository(repo, store, max_file_bytes=1_000_000)
        assert result.skipped_large == 1
        assert store.file_record("src/bundle.js") is None

    def test_broken_files_still_index_recovered_symbols(
        self, repo: Path, store: Store
    ) -> None:
        (repo / "src" / "wip.py").write_bytes(b"def done():\n    pass\n\ndef half(\n")
        result = indexer.index_repository(repo, store)
        assert result.indexed == 3
        assert [r.path for r in store.lookup_exact("done")] == ["src/wip.py"]

    def test_reindexing_is_idempotent(self, repo: Path, store: Store) -> None:
        indexer.index_repository(repo, store)
        first = store.stats()
        indexer.index_repository(repo, store)
        assert store.stats() == first

    def test_fallback_walk_skips_junk_directories(
        self, repo: Path, store: Store
    ) -> None:
        junk = repo / "node_modules" / "lib"
        junk.mkdir(parents=True)
        (junk / "dep.js").write_bytes(b"module.exports = 1;\n")
        indexer.index_repository(repo, store)
        assert store.file_record("node_modules/lib/dep.js") is None


@pytest.mark.skipif(GIT is None, reason="git not on PATH")
class TestGitignore:
    def test_gitignored_files_are_not_indexed(self, repo: Path, store: Store) -> None:
        subprocess.run(
            [GIT, "init", "--quiet", str(repo)], check=True, capture_output=True
        )
        (repo / ".gitignore").write_text("generated.py\n", encoding="utf-8")
        (repo / "src" / "generated.py").write_bytes(b"X = 1\n")
        result = indexer.index_repository(repo, store)
        assert result.indexed == 2
        assert store.file_record("src/generated.py") is None
        assert store.file_record("src/app.py") is not None
