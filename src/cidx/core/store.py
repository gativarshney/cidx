"""SQLite persistence for the cidx index.

Discipline (AGENTS.md): WAL mode, ``synchronous=NORMAL``, foreign keys on,
every multi-row mutation inside one explicit transaction, and
``schema_version`` checked on open. The FTS5 table uses external content
(``content='symbols'``), so this module keeps it in sync inside the same
transaction as each mutation.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from types import TracebackType

from cidx.core import resolve
from cidx.core.schema import DROP_SQL, SCHEMA_SQL, SCHEMA_VERSION
from cidx.extractors.base import Extraction


@dataclass(frozen=True, slots=True)
class SymbolRow:
    """One symbol as returned by store queries, with its file location."""

    id: int
    name: str
    qualified_name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    signature: str | None


class Store:
    """One open index database. Use as a context manager or call close()."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, db_path: str | Path) -> Store:
        """Open (creating or rebuilding if needed) the index at *db_path*."""
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        _ensure_schema(connection)
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def replace_file(
        self,
        path: str,
        language: str,
        content_hash: str,
        mtime: float,
        extraction: Extraction,
    ) -> None:
        """Atomically replace everything known about one file.

        One transaction: delete the file's old rows, insert the new ones,
        update the file record. A crash mid-update rolls back cleanly.
        """
        connection = self._connection
        connection.execute("BEGIN")
        try:
            self._delete_file_rows(path)
            cursor = connection.execute(
                "INSERT INTO files (path, language, content_hash, mtime,"
                " indexed_at) VALUES (?, ?, ?, ?, ?)",
                (path, language, content_hash, mtime, time.time()),
            )
            file_id = cursor.lastrowid
            id_by_qname: dict[str, int] = {}
            for symbol in extraction.symbols:
                parent_id = (
                    id_by_qname.get(symbol.parent)
                    if symbol.parent is not None
                    else None
                )
                cursor = connection.execute(
                    "INSERT INTO symbols (file_id, name, qualified_name, kind,"
                    " start_line, end_line, signature, parent_id)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        file_id,
                        symbol.name,
                        symbol.qualified_name,
                        symbol.kind,
                        symbol.start_line,
                        symbol.end_line,
                        symbol.signature,
                        parent_id,
                    ),
                )
                assert cursor.lastrowid is not None
                id_by_qname.setdefault(symbol.qualified_name, cursor.lastrowid)
            connection.executemany(
                "INSERT INTO refs (file_id, name, line, resolved_symbol_id,"
                " confidence) VALUES (?, ?, ?, NULL, 'name-only')",
                [(file_id, ref.name, ref.line) for ref in extraction.references],
            )
            connection.execute(
                "INSERT INTO symbols_fts (rowid, name, qualified_name, signature)"
                " SELECT id, name, qualified_name, signature FROM symbols"
                " WHERE file_id = ?",
                (file_id,),
            )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    def remove_file(self, path: str) -> None:
        """Remove one file and all its rows; a no-op if the path is unknown."""
        connection = self._connection
        connection.execute("BEGIN")
        try:
            self._delete_file_rows(path)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    def resolve_references(self) -> None:
        """Recompute the resolution cascade over the whole index.

        Called after mutations (and once after a cold walk) so incremental
        and cold indexes agree on resolved targets.
        """
        connection = self._connection
        connection.execute("BEGIN")
        try:
            resolve.resolve_all(connection)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    def file_record(self, path: str) -> sqlite3.Row | None:
        """The files row for *path* (id, hashes, times), or None."""
        return self._connection.execute(
            "SELECT * FROM files WHERE path = ?", (path,)
        ).fetchone()

    def lookup_exact(self, name: str, limit: int = 50) -> list[SymbolRow]:
        """Symbols whose name or qualified name equals *name* exactly."""
        rows = self._connection.execute(
            "SELECT s.id, s.name, s.qualified_name, s.kind, f.path,"
            " s.start_line, s.end_line, s.signature"
            " FROM symbols s JOIN files f ON f.id = s.file_id"
            " WHERE s.name = ? OR s.qualified_name = ?"
            " ORDER BY f.path, s.start_line LIMIT ?",
            (name, name, limit),
        ).fetchall()
        return [SymbolRow(**row) for row in rows]

    def search(self, query: str, limit: int = 50) -> list[SymbolRow]:
        """Fuzzy symbol search via FTS5 prefix matching, best matches first."""
        match = _fts_match_expression(query)
        if match is None:
            return []
        rows = self._connection.execute(
            "SELECT s.id, s.name, s.qualified_name, s.kind, f.path,"
            " s.start_line, s.end_line, s.signature"
            " FROM symbols_fts JOIN symbols s ON s.id = symbols_fts.rowid"
            " JOIN files f ON f.id = s.file_id"
            " WHERE symbols_fts MATCH ? ORDER BY rank LIMIT ?",
            (match, limit),
        ).fetchall()
        return [SymbolRow(**row) for row in rows]

    def indexed_paths(self) -> set[str]:
        """Every file path currently in the index."""
        return {
            row["path"] for row in self._connection.execute("SELECT path FROM files")
        }

    def snapshot(self) -> dict[str, set[tuple]]:
        """Value-level row sets for convergence comparison.

        Ids and timestamps are excluded on purpose: two databases describing
        the same repository state must produce equal snapshots.
        """
        connection = self._connection
        files = {
            (row["path"], row["language"], row["content_hash"])
            for row in connection.execute(
                "SELECT path, language, content_hash FROM files"
            )
        }
        symbols = {
            tuple(row)
            for row in connection.execute(
                "SELECT f.path, s.name, s.qualified_name, s.kind, s.start_line,"
                " s.end_line, s.signature, p.qualified_name"
                " FROM symbols s JOIN files f ON f.id = s.file_id"
                " LEFT JOIN symbols p ON p.id = s.parent_id"
            )
        }
        refs = {
            tuple(row)
            for row in connection.execute(
                "SELECT f.path, r.name, r.line, r.confidence,"
                " rf.path, rs.qualified_name"
                " FROM refs r JOIN files f ON f.id = r.file_id"
                " LEFT JOIN symbols rs ON rs.id = r.resolved_symbol_id"
                " LEFT JOIN files rf ON rf.id = rs.file_id"
            )
        }
        return {"files": files, "symbols": symbols, "refs": refs}

    def stats(self) -> dict[str, int]:
        """Row counts: files, symbols, refs."""
        counts = {}
        for table in ("files", "symbols", "refs"):
            row = self._connection.execute(
                f"SELECT COUNT(*) AS n FROM {table}"  # noqa: S608 - fixed names
            ).fetchone()
            counts[table] = row["n"]
        return counts

    def _delete_file_rows(self, path: str) -> None:
        """Inside a caller-managed transaction: drop one file's rows + FTS."""
        connection = self._connection
        row = connection.execute(
            "SELECT id FROM files WHERE path = ?", (path,)
        ).fetchone()
        if row is None:
            return
        file_id = row["id"]
        connection.execute(
            "INSERT INTO symbols_fts (symbols_fts, rowid, name, qualified_name,"
            " signature) SELECT 'delete', id, name, qualified_name, signature"
            " FROM symbols WHERE file_id = ?",
            (file_id,),
        )
        # other files' refs may resolve into this file's symbols; detach them
        # (the resolution recompute after every mutation re-derives truth)
        connection.execute(
            "UPDATE refs SET resolved_symbol_id = NULL, confidence = 'name-only'"
            " WHERE resolved_symbol_id IN"
            " (SELECT id FROM symbols WHERE file_id = ?)",
            (file_id,),
        )
        connection.execute("DELETE FROM files WHERE id = ?", (file_id,))


def _ensure_schema(connection: sqlite3.Connection) -> None:
    """Create the schema, or rebuild it when the stored version disagrees."""
    stored = _stored_schema_version(connection)
    if stored == SCHEMA_VERSION:
        return
    connection.executescript(DROP_SQL)
    connection.executescript(SCHEMA_SQL)
    connection.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    connection.execute(
        "INSERT INTO meta (key, value) VALUES ('engine_version', ?)",
        (version("cidx"),),
    )


def _stored_schema_version(connection: sqlite3.Connection) -> int | None:
    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
    ).fetchone()
    if table is None:
        return None
    row = connection.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        return None
    try:
        return int(row["value"])
    except ValueError:
        return None


def _fts_match_expression(query: str) -> str | None:
    """Turn free text into a safe FTS5 prefix query, or None if empty."""
    tokens = re.findall(r"\w+", query)
    if not tokens:
        return None
    return " ".join(f'"{token}"*' for token in tokens)
