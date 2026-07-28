"""The cidx MCP server: five read-only tools over stdio.

Read-only is a security stance: a tool that cannot write or execute has no
prompt-injection blast radius (ADR-006). Tool descriptions are prompts —
wording changes agent behavior, so treat them as a measured surface and A/B
against the benchmark before rewording (AGENTS.md).

Every tool opens a fresh read connection per call (WAL keeps readers and the
watcher's writer independent), fits its response to a token budget, stamps
freshness, and fails open: on any miss the answer says so and recommends
grep, so the worst case with cidx equals not having it.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from cidx.core import query as query_layer
from cidx.core.store import Store, SymbolRow
from cidx.ranking import budget, scorer


def create_server(repo_root: str | Path, db_path: str | Path) -> FastMCP:
    """Build the stdio server for one repository's index."""
    root = Path(repo_root).resolve()
    database = Path(db_path)
    server = FastMCP("cidx")

    def open_store() -> Store | None:
        if not database.exists():
            return None
        return Store.open(database)

    @server.tool(
        description=(
            "Fuzzy-search symbols (functions, classes, methods, consts) by"
            " name across the whole repository. Returns ranked, terse"
            " `qualified_name kind path:line signature` rows. Start here when"
            " you only roughly know a name."
        )
    )
    def search_symbols(query: str, max_tokens: int = budget.DEFAULT_MAX_TOKENS) -> str:
        store = open_store()
        if store is None:
            return budget.fail_open_message(f"no index for {root}")
        with store:
            rows, total = scorer.search_symbols(store, query, limit=100)
            if not rows:
                return _empty(store, f"no symbols match {query!r}")
            return budget.shape(
                [_symbol_line(row) for row in rows], total, store, max_tokens
            ).render()

    @server.tool(
        description=(
            "Find where a symbol is defined. Give the exact name or qualified"
            " name (`Repo.save`). Returns definition locations with"
            " signatures — verify by reading the cited file:line."
        )
    )
    def find_definition(name: str, max_tokens: int = budget.DEFAULT_MAX_TOKENS) -> str:
        store = open_store()
        if store is None:
            return budget.fail_open_message(f"no index for {root}")
        with store:
            rows = query_layer.find_definition(store, name)
            if not rows:
                return _empty(store, f"no definition of {name!r} in the index")
            return budget.shape(
                [_symbol_line(row) for row in rows], len(rows), store, max_tokens
            ).render()

    @server.tool(
        description=(
            "Find every usage of a symbol: calls, constructions, decorators,"
            " JSX usages. Each row is `path:line name [confidence]` with the"
            " resolved target when known; confidence `exact` and `import`"
            " beat `name-only`."
        )
    )
    def find_references(name: str, max_tokens: int = budget.DEFAULT_MAX_TOKENS) -> str:
        store = open_store()
        if store is None:
            return budget.fail_open_message(f"no index for {root}")
        with store:
            rows = query_layer.find_references(store, name)
            if not rows:
                return _empty(store, f"no references to {name!r} in the index")
            lines = [
                f"{r.path}:{r.line}  {r.name}  [{r.confidence}]"
                + (
                    f"  -> {r.resolved_qualified_name} ({r.resolved_path})"
                    if r.resolved_qualified_name
                    else ""
                )
                for r in rows
            ]
            return budget.shape(lines, len(rows), store, max_tokens).render()

    @server.tool(
        description=(
            "Outline one file: every symbol it defines, in source order, with"
            " nesting and signatures. Use a repo-relative path with forward"
            " slashes (`src/app.py`). Cheaper than reading the file."
        )
    )
    def outline_file(path: str, max_tokens: int = budget.DEFAULT_MAX_TOKENS) -> str:
        store = open_store()
        if store is None:
            return budget.fail_open_message(f"no index for {root}")
        with store:
            rows = query_layer.outline_file(store, Path(path).as_posix())
            if not rows:
                return _empty(
                    store, f"no symbols for {path!r} (is the path repo-relative?)"
                )
            lines = [
                f"{r.start_line}  {r.qualified_name}  {r.kind}"
                + (f"  {r.signature}" if r.signature else "")
                for r in rows
            ]
            return budget.shape(lines, len(rows), store, max_tokens).render()

    @server.tool(
        description=(
            "A ranked map of the repository: most-referenced files first,"
            " each with its top-level symbols. Use this to orient in an"
            " unfamiliar codebase before searching."
        )
    )
    def repo_map(max_tokens: int = budget.DEFAULT_MAX_TOKENS) -> str:
        store = open_store()
        if store is None:
            return budget.fail_open_message(f"no index for {root}")
        with store:
            entries = query_layer.repo_map(store)
            if not entries:
                return _empty(store, "the index is empty")
            lines = [
                f"{e.path}  ({e.language}, {e.symbol_count} symbols,"
                f" {e.incoming_refs} inbound)  " + (", ".join(e.top_symbols) or "-")
                for e in entries
            ]
            return budget.shape(lines, len(entries), store, max_tokens).render()

    return server


def _symbol_line(row: SymbolRow) -> str:
    line = f"{row.qualified_name}  {row.kind}  {row.path}:{row.start_line}"
    if row.signature:
        line += f"  {row.signature}"
    return line


def _empty(store: Store, reason: str) -> str:
    return budget.shape(
        [], 0, store, notes=(budget.fail_open_message(reason),)
    ).render()
