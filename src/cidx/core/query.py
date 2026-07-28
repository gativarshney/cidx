"""Query-layer data functions: definitions, references, outline, repo map.

Both consumers (the CLI and, later, the MCP server) call these; neither
contains logic of its own (ARCHITECTURE.md). Ranking and token budgeting
arrive in Phase 7 — until then, orderings are deterministic but unweighted.
"""

from __future__ import annotations

from dataclasses import dataclass

from cidx.core.store import Store, SymbolRow

_DEFINITION_KINDS = ("function", "class", "method", "const")


@dataclass(frozen=True, slots=True)
class ReferenceRow:
    """One usage site, with whatever resolution the cascade produced."""

    path: str
    line: int
    name: str
    confidence: str
    resolved_path: str | None
    resolved_qualified_name: str | None


@dataclass(frozen=True, slots=True)
class OutlineRow:
    """One symbol in a file's outline; parent gives the nesting."""

    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    signature: str | None
    parent: str | None


@dataclass(frozen=True, slots=True)
class RepoMapEntry:
    """One file in the repo map, with its top-level shape and popularity."""

    path: str
    language: str
    symbol_count: int
    incoming_refs: int
    top_symbols: tuple[str, ...]


def find_definition(store: Store, name: str, limit: int = 50) -> list[SymbolRow]:
    """Definitions whose name or qualified name equals *name* exactly."""
    placeholders = ", ".join("?" for _ in _DEFINITION_KINDS)
    rows = store.connection.execute(
        "SELECT s.id, s.name, s.qualified_name, s.kind, f.path,"
        " s.start_line, s.end_line, s.signature"
        " FROM symbols s JOIN files f ON f.id = s.file_id"
        f" WHERE (s.name = ? OR s.qualified_name = ?) AND s.kind IN ({placeholders})"
        " ORDER BY f.path, s.start_line LIMIT ?",
        (name, name, *_DEFINITION_KINDS, limit),
    ).fetchall()
    return [SymbolRow(**row) for row in rows]


def find_references(store: Store, name: str, limit: int = 200) -> list[ReferenceRow]:
    """Usage sites for *name*: resolved hits first, then unresolved name matches.

    When *name* is qualified (``Repo.save``), references resolved to that
    exact definition are returned; the bare trailing name is used for the
    unresolved name-only matches.
    """
    bare = name.rsplit(".", maxsplit=1)[-1]
    definition_ids = [row.id for row in find_definition(store, name)]
    id_placeholders = ", ".join("?" for _ in definition_ids) or "NULL"
    rows = store.connection.execute(
        "SELECT f.path, r.line, r.name, r.confidence, rf.path AS resolved_path,"
        " rs.qualified_name AS resolved_qualified_name"
        " FROM refs r JOIN files f ON f.id = r.file_id"
        " LEFT JOIN symbols rs ON rs.id = r.resolved_symbol_id"
        " LEFT JOIN files rf ON rf.id = rs.file_id"
        f" WHERE r.resolved_symbol_id IN ({id_placeholders})"
        " OR (r.name = ? AND r.resolved_symbol_id IS NULL)"
        " ORDER BY (r.resolved_symbol_id IS NULL), f.path, r.line LIMIT ?",
        (*definition_ids, bare, limit),
    ).fetchall()
    return [ReferenceRow(**row) for row in rows]


def outline_file(store: Store, path: str) -> list[OutlineRow]:
    """Every symbol in *path*, in source order, with parent qualified names."""
    rows = store.connection.execute(
        "SELECT s.name, s.qualified_name, s.kind, s.start_line, s.end_line,"
        " s.signature, p.qualified_name AS parent"
        " FROM symbols s JOIN files f ON f.id = s.file_id"
        " LEFT JOIN symbols p ON p.id = s.parent_id"
        " WHERE f.path = ?"
        " ORDER BY s.start_line, s.qualified_name",
        (path,),
    ).fetchall()
    return [OutlineRow(**row) for row in rows]


def repo_map(
    store: Store, limit: int = 50, top_symbols_per_file: int = 10
) -> list[RepoMapEntry]:
    """The repository's shape: files by incoming-reference popularity.

    Popularity is the count of references (from any file) resolved into the
    file's symbols — a data-layer signal the Phase 7 ranker will weight.
    """
    # grouped aggregations, not per-file correlated subqueries: one pass over
    # symbols and refs regardless of file count
    rows = store.connection.execute(
        "SELECT f.id, f.path, f.language,"
        " COALESCE(sc.n, 0) AS symbol_count,"
        " COALESCE(ir.n, 0) AS incoming_refs"
        " FROM files f"
        " LEFT JOIN (SELECT file_id, COUNT(*) AS n FROM symbols"
        "   GROUP BY file_id) sc ON sc.file_id = f.id"
        " LEFT JOIN (SELECT rs.file_id AS target, COUNT(*) AS n"
        "   FROM refs r JOIN symbols rs ON rs.id = r.resolved_symbol_id"
        "   WHERE r.file_id != rs.file_id GROUP BY rs.file_id) ir"
        "   ON ir.target = f.id"
        " ORDER BY incoming_refs DESC, f.path LIMIT ?",
        (limit,),
    ).fetchall()
    file_ids = [row["id"] for row in rows]
    id_placeholders = ", ".join("?" for _ in file_ids) or "NULL"
    top_by_file: dict[int, list[str]] = {}
    for symbol_row in store.connection.execute(
        "SELECT file_id, qualified_name FROM ("
        " SELECT s.file_id, s.qualified_name,"
        " ROW_NUMBER() OVER (PARTITION BY s.file_id ORDER BY s.start_line)"
        "   AS rank_in_file"
        " FROM symbols s"
        f" WHERE s.file_id IN ({id_placeholders})"
        " AND s.parent_id IS NULL AND s.kind != 'import'"
        ") WHERE rank_in_file <= ?",
        (*file_ids, top_symbols_per_file),
    ):
        top_by_file.setdefault(symbol_row["file_id"], []).append(
            symbol_row["qualified_name"]
        )
    return [
        RepoMapEntry(
            path=row["path"],
            language=row["language"],
            symbol_count=row["symbol_count"],
            incoming_refs=row["incoming_refs"],
            top_symbols=tuple(top_by_file.get(row["id"], [])),
        )
        for row in rows
    ]
