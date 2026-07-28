"""Tests for the reference-resolution cascade."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from cidx.core import incremental, indexer
from cidx.core.store import Store


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    with Store.open(tmp_path / "cache" / "index.db") as opened:
        yield opened


def refs_view(store: Store) -> dict[tuple[str, str, int], tuple]:
    """(ref path, name, line) -> (confidence, resolved path, resolved qname)."""
    rows = store._connection.execute(
        "SELECT f.path, r.name, r.line, r.confidence, rf.path, rs.qualified_name"
        " FROM refs r JOIN files f ON f.id = r.file_id"
        " LEFT JOIN symbols rs ON rs.id = r.resolved_symbol_id"
        " LEFT JOIN files rf ON rf.id = rs.file_id"
    )
    return {(r[0], r[1], r[2]): (r[3], r[4], r[5]) for r in rows}


def index(repo: Path, store: Store) -> None:
    indexer.index_repository(repo, store)


class TestSameFileTier:
    def test_same_file_call_is_exact(self, repo: Path, store: Store) -> None:
        (repo / "a.py").write_bytes(
            b"def helper():\n    return 1\n\n\ndef main():\n    return helper()\n"
        )
        index(repo, store)
        assert refs_view(store)[("a.py", "helper", 6)] == ("exact", "a.py", "helper")

    def test_recursive_call_resolves_to_its_own_function(
        self, repo: Path, store: Store
    ) -> None:
        (repo / "a.py").write_bytes(
            b"def loop(n):\n    return loop(n - 1)\n\n\nclass loop:\n    pass\n"
        )
        index(repo, store)
        confidence, path, qname = refs_view(store)[("a.py", "loop", 2)]
        assert confidence == "exact"
        assert (path, qname) == ("a.py", "loop")


class TestImportTier:
    def test_from_import_is_followed_to_source(self, repo: Path, store: Store) -> None:
        (repo / "pkg").mkdir()
        (repo / "pkg" / "util.py").write_bytes(b"def tool():\n    return 1\n")
        (repo / "main.py").write_bytes(
            b"from pkg.util import tool\n\nresult = tool()\n"
        )
        index(repo, store)
        assert refs_view(store)[("main.py", "tool", 3)] == (
            "import",
            "pkg/util.py",
            "tool",
        )

    def test_relative_import_is_followed(self, repo: Path, store: Store) -> None:
        (repo / "pkg").mkdir()
        (repo / "pkg" / "sibling.py").write_bytes(b"def near():\n    return 1\n")
        (repo / "pkg" / "user.py").write_bytes(
            b"from .sibling import near\n\nvalue = near()\n"
        )
        index(repo, store)
        assert refs_view(store)[("pkg/user.py", "near", 3)] == (
            "import",
            "pkg/sibling.py",
            "near",
        )

    def test_js_relative_import_is_followed(self, repo: Path, store: Store) -> None:
        (repo / "io.ts").write_bytes(b"export function writeFile(p: string): void {}\n")
        (repo / "main.ts").write_bytes(
            b'import { writeFile } from "./io";\n\nwriteFile("x");\n'
        )
        index(repo, store)
        assert refs_view(store)[("main.ts", "writeFile", 3)] == (
            "import",
            "io.ts",
            "writeFile",
        )

    def test_stdlib_import_falls_through_the_cascade(
        self, repo: Path, store: Store
    ) -> None:
        (repo / "a.py").write_bytes(
            b"from functools import cache\n\nvalue = cache(len)\n"
        )
        index(repo, store)
        confidence, path, _ = refs_view(store)[("a.py", "cache", 3)]
        assert confidence == "name-only"
        assert path is None  # functools.py is not in the index


class TestGlobalTier:
    def test_unique_global_name_resolves_name_only(
        self, repo: Path, store: Store
    ) -> None:
        (repo / "lib.py").write_bytes(b"def unique_thing():\n    return 1\n")
        (repo / "user.py").write_bytes(b"x = unique_thing()\n")
        index(repo, store)
        assert refs_view(store)[("user.py", "unique_thing", 1)] == (
            "name-only",
            "lib.py",
            "unique_thing",
        )

    def test_ambiguous_global_name_stays_unresolved(
        self, repo: Path, store: Store
    ) -> None:
        (repo / "one.py").write_bytes(b"def common():\n    return 1\n")
        (repo / "two.py").write_bytes(b"def common():\n    return 2\n")
        (repo / "user.py").write_bytes(b"x = common()\n")
        index(repo, store)
        assert refs_view(store)[("user.py", "common", 1)] == (
            "name-only",
            None,
            None,
        )


class TestResolutionTracksEdits:
    def test_moving_a_definition_flips_the_resolution(
        self, repo: Path, store: Store
    ) -> None:
        (repo / "lib.py").write_bytes(b"def target():\n    return 1\n")
        (repo / "user.py").write_bytes(b"x = target()\n")
        index(repo, store)
        assert refs_view(store)[("user.py", "target", 1)][1] == "lib.py"

        (repo / "lib.py").write_bytes(b"def renamed():\n    return 1\n")
        (repo / "other.py").write_bytes(b"def target():\n    return 2\n")
        incremental.refresh_path(store, repo, "lib.py")
        incremental.refresh_path(store, repo, "other.py")
        assert refs_view(store)[("user.py", "target", 1)][1] == "other.py"

    def test_new_duplicate_definition_demotes_to_unresolved(
        self, repo: Path, store: Store
    ) -> None:
        (repo / "lib.py").write_bytes(b"def target():\n    return 1\n")
        (repo / "user.py").write_bytes(b"x = target()\n")
        index(repo, store)
        (repo / "dupe.py").write_bytes(b"def target():\n    return 2\n")
        incremental.refresh_path(store, repo, "dupe.py")
        assert refs_view(store)[("user.py", "target", 1)] == (
            "name-only",
            None,
            None,
        )
