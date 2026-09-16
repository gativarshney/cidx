"""Schema work-contract tests: foreign keys must be backed by indexes.

``files -> symbols`` and ``files -> refs`` cascade on delete, and ``symbols``
references itself through ``parent_id``. SQLite enforces all three by looking
up the child column, so without an index every ``replace_file`` walked the
whole ``symbols`` and ``refs`` tables: on Django (76k symbols, 207k refs) one
file replacement cost 361 ms and a re-index over an existing index ran past
eleven minutes, versus 1.7 ms and a few seconds with the indexes (ADR-016).

These tests pin the contract itself -- coverage and query plans -- so they
cannot flake on timing and will catch any future foreign key added without an
index.
"""

from __future__ import annotations

import sqlite3

from cidx.core.store import Store


def _tables(con: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL"
        )
    ]


def _foreign_keys(con: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    """(child column, parent table) for every foreign key on *table*."""
    rows = con.execute(f"PRAGMA foreign_key_list({table})")
    return [(row[3], row[2]) for row in rows]


def _indexed_leading_columns(con: sqlite3.Connection, table: str) -> set[str]:
    """Columns that lead some index on *table*; only a leading column seeks."""
    leading: set[str] = set()
    for index in con.execute(f"PRAGMA index_list({table})"):
        for info in con.execute(f"PRAGMA index_info({index[1]})"):
            if info[0] == 0:
                leading.add(info[2])
    return leading


def test_every_foreign_key_column_is_indexed(tmp_path):
    with Store.open(tmp_path / "index.db") as store:
        con = store.connection
        missing = [
            f"{table}.{column} -> {parent}"
            for table in _tables(con)
            for column, parent in _foreign_keys(con, table)
            if column not in _indexed_leading_columns(con, table)
        ]
    assert not missing, (
        "foreign-key columns without a leading index: "
        + ", ".join(missing)
        + " -- every cascade and constraint check on them scans the whole table"
    )


def test_cascade_and_parent_lookups_seek_instead_of_scan(tmp_path):
    lookups = (
        "SELECT id FROM symbols WHERE file_id = ?",
        "SELECT id FROM refs WHERE file_id = ?",
        "SELECT id FROM symbols WHERE parent_id = ?",
    )
    with Store.open(tmp_path / "index.db") as store:
        con = store.connection
        for sql in lookups:
            plan = " ".join(
                row[3] for row in con.execute("EXPLAIN QUERY PLAN " + sql, (1,))
            )
            assert "SCAN" not in plan and "INDEX" in plan, (
                f"{sql!r} plans as {plan!r}; this lookup runs once per file"
                " replacement and must use an index"
            )
