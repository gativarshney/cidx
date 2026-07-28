"""Tests for the SQLite store: pragmas, transactions, FTS sync, rebuilds."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from cidx.core import store as store_mod
from cidx.core.schema import SCHEMA_VERSION
from cidx.core.store import Store
from cidx.extractors.base import Extraction, Reference, Symbol

FUNC = Symbol(
    name="save",
    qualified_name="Repo.save",
    kind="method",
    start_line=10,
    end_line=14,
    signature="def save(self) -> None",
    parent="Repo",
)
KLASS = Symbol(
    name="Repo", qualified_name="Repo", kind="class", start_line=5, end_line=20
)
EXTRACTION = Extraction(
    symbols=(KLASS, FUNC),
    references=(Reference(name="validate", line=12),),
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "index.db"


@pytest.fixture
def opened(db_path: Path) -> Iterator[Store]:
    with Store.open(db_path) as opened_store:
        yield opened_store


class TestOpen:
    def test_creates_parent_directories_and_file(self, db_path: Path) -> None:
        with Store.open(db_path):
            assert db_path.exists()

    def test_pragmas_match_the_contract(self, opened: Store) -> None:
        connection = opened._connection
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL

    def test_schema_version_is_recorded(self, opened: Store) -> None:
        row = opened._connection.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        assert int(row["value"]) == SCHEMA_VERSION

    def test_foreign_schema_version_triggers_rebuild(self, db_path: Path) -> None:
        with Store.open(db_path) as first:
            first.replace_file("a.py", "python", "h1", 1.0, EXTRACTION)
            first._connection.execute(
                "UPDATE meta SET value = '9999' WHERE key = 'schema_version'"
            )
        with Store.open(db_path) as second:
            assert second.stats() == {"files": 0, "symbols": 0, "refs": 0}


class TestReplaceFile:
    def test_inserts_file_symbols_and_refs(self, opened: Store) -> None:
        opened.replace_file("a.py", "python", "h1", 1.0, EXTRACTION)
        assert opened.stats() == {"files": 1, "symbols": 2, "refs": 1}

    def test_parent_id_links_method_to_class(self, opened: Store) -> None:
        opened.replace_file("a.py", "python", "h1", 1.0, EXTRACTION)
        row = opened._connection.execute(
            "SELECT p.qualified_name AS parent FROM symbols s"
            " JOIN symbols p ON p.id = s.parent_id"
            " WHERE s.qualified_name = 'Repo.save'"
        ).fetchone()
        assert row["parent"] == "Repo"

    def test_replacing_removes_stale_rows(self, opened: Store) -> None:
        opened.replace_file("a.py", "python", "h1", 1.0, EXTRACTION)
        smaller = Extraction(symbols=(KLASS,), references=())
        opened.replace_file("a.py", "python", "h2", 2.0, smaller)
        assert opened.stats() == {"files": 1, "symbols": 1, "refs": 0}
        assert opened.file_record("a.py")["content_hash"] == "h2"

    def test_failure_mid_transaction_rolls_back_completely(self, opened: Store) -> None:
        opened.replace_file("a.py", "python", "h1", 1.0, EXTRACTION)
        bad_symbol = Symbol(
            name="broken",
            qualified_name="broken",
            kind=None,  # type: ignore[arg-type] - violates NOT NULL mid-insert
            start_line=1,
            end_line=1,
        )
        with pytest.raises(sqlite3.IntegrityError):
            opened.replace_file(
                "a.py", "python", "h2", 2.0, Extraction((KLASS, bad_symbol), ())
            )
        assert opened.stats() == {"files": 1, "symbols": 2, "refs": 1}
        assert opened.file_record("a.py")["content_hash"] == "h1"


class TestRemoveFile:
    def test_cascades_symbols_and_refs(self, opened: Store) -> None:
        opened.replace_file("a.py", "python", "h1", 1.0, EXTRACTION)
        opened.remove_file("a.py")
        assert opened.stats() == {"files": 0, "symbols": 0, "refs": 0}

    def test_unknown_path_is_a_noop(self, opened: Store) -> None:
        opened.remove_file("never/indexed.py")
        assert opened.stats() == {"files": 0, "symbols": 0, "refs": 0}


class TestQueries:
    def test_lookup_exact_matches_name_and_qualified_name(self, opened: Store) -> None:
        opened.replace_file("a.py", "python", "h1", 1.0, EXTRACTION)
        by_name = opened.lookup_exact("save")
        by_qname = opened.lookup_exact("Repo.save")
        assert [r.qualified_name for r in by_name] == ["Repo.save"]
        assert by_qname == by_name
        assert by_name[0].path == "a.py"
        assert by_name[0].start_line == 10

    def test_fts_search_finds_by_prefix(self, opened: Store) -> None:
        opened.replace_file("a.py", "python", "h1", 1.0, EXTRACTION)
        assert [r.qualified_name for r in opened.search("sav")] == ["Repo.save"]

    def test_fts_stays_in_sync_after_replace(self, opened: Store) -> None:
        opened.replace_file("a.py", "python", "h1", 1.0, EXTRACTION)
        renamed = Symbol(
            name="persist",
            qualified_name="Repo.persist",
            kind="method",
            start_line=10,
            end_line=14,
            parent="Repo",
        )
        opened.replace_file(
            "a.py", "python", "h2", 2.0, Extraction((KLASS, renamed), ())
        )
        assert opened.search("save") == []
        assert [r.qualified_name for r in opened.search("persist")] == ["Repo.persist"]

    def test_fts_stays_in_sync_after_remove(self, opened: Store) -> None:
        opened.replace_file("a.py", "python", "h1", 1.0, EXTRACTION)
        opened.remove_file("a.py")
        assert opened.search("save") == []

    def test_fts_ignores_empty_and_symbol_only_queries(self, opened: Store) -> None:
        assert opened.search("") == []
        assert opened.search("!!! ***") == []

    def test_refs_are_stored_name_only_until_resolution(self, opened: Store) -> None:
        opened.replace_file("a.py", "python", "h1", 1.0, EXTRACTION)
        row = opened._connection.execute("SELECT * FROM refs").fetchone()
        assert row["name"] == "validate"
        assert row["line"] == 12
        assert row["resolved_symbol_id"] is None
        assert row["confidence"] == "name-only"


class TestMatchExpression:
    def test_tokens_become_quoted_prefixes(self) -> None:
        assert store_mod._fts_match_expression("user repo") == '"user"* "repo"*'

    def test_punctuation_is_stripped_not_injected(self) -> None:
        assert store_mod._fts_match_expression('save"; DROP') == '"save"* "DROP"*'
