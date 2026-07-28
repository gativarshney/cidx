"""Tests for the query-layer data functions."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from cidx.core import indexer, query
from cidx.core.store import Store

LIB = b"""\
def tool():
    return 1


class Repo:
    def save(self):
        return tool()
"""

MAIN = b"""\
from lib import tool

def run(repo):
    tool()
    return repo.save()
"""


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "lib.py").write_bytes(LIB)
    (root / "main.py").write_bytes(MAIN)
    with Store.open(tmp_path / "cache" / "index.db") as opened:
        indexer.index_repository(root, opened)
        yield opened


class TestFindDefinition:
    def test_finds_by_bare_and_qualified_name(self, store: Store) -> None:
        by_bare = query.find_definition(store, "save")
        by_qualified = query.find_definition(store, "Repo.save")
        assert by_bare == by_qualified
        assert by_bare[0].path == "lib.py"
        assert by_bare[0].kind == "method"

    def test_import_bindings_are_not_definitions(self, store: Store) -> None:
        rows = query.find_definition(store, "tool")
        assert [r.path for r in rows] == ["lib.py"]  # main.py's import excluded

    def test_unknown_name_returns_empty(self, store: Store) -> None:
        assert query.find_definition(store, "nonexistent") == []


class TestFindReferences:
    def test_resolved_references_come_with_targets(self, store: Store) -> None:
        rows = query.find_references(store, "tool")
        locations = [(r.path, r.line, r.confidence) for r in rows]
        assert ("lib.py", 7, "exact") in locations  # call inside Repo.save
        assert ("main.py", 4, "import") in locations  # call via the import
        for row in rows:
            assert row.resolved_qualified_name == "tool"
            assert row.resolved_path == "lib.py"

    def test_qualified_name_narrows_to_one_definition(self, store: Store) -> None:
        rows = query.find_references(store, "Repo.save")
        assert [(r.path, r.line) for r in rows] == [("main.py", 5)]

    def test_unknown_name_returns_empty(self, store: Store) -> None:
        assert query.find_references(store, "nonexistent") == []


class TestOutlineFile:
    def test_symbols_in_source_order_with_parents(self, store: Store) -> None:
        rows = query.outline_file(store, "lib.py")
        assert [(r.qualified_name, r.kind, r.parent) for r in rows] == [
            ("tool", "function", None),
            ("Repo", "class", None),
            ("Repo.save", "method", "Repo"),
        ]

    def test_unknown_path_returns_empty(self, store: Store) -> None:
        assert query.outline_file(store, "ghost.py") == []


class TestRepoMap:
    def test_files_ordered_by_incoming_references(self, store: Store) -> None:
        entries = query.repo_map(store)
        assert [e.path for e in entries] == ["lib.py", "main.py"]
        assert entries[0].incoming_refs > entries[1].incoming_refs

    def test_top_symbols_are_top_level_definitions_only(self, store: Store) -> None:
        by_path = {e.path: e for e in query.repo_map(store)}
        assert by_path["lib.py"].top_symbols == ("tool", "Repo")
        assert by_path["main.py"].top_symbols == ("run",)  # import excluded
