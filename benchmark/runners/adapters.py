"""Contestant adapters: each exposes retrieval tools to the scripted agent.

Every contestant runs under identical conditions; the ONLY variable is the
retrieval toolset. Common tools (read_file, final_answer) are provided by the
runner itself, not by adapters. Competitor adapters are accepted by pull
request and must implement the same three methods (methodology.md).

The cidx adapter calls the same library functions the MCP server serves;
transport is not what this benchmark measures (the MCP wire protocol has its
own integration tests).
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cidx.core import indexer
from cidx.core import query as query_layer
from cidx.core.store import Store
from cidx.ranking import budget, scorer

_MAX_GREP_RESULTS = 50


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Provider-agnostic tool description shown to the model."""

    name: str
    description: str
    parameters: dict[str, str]  # argument name -> description


class GrepAdapter:
    """The baseline: regex search over the repository, nothing else."""

    name = "grep"

    def __init__(self) -> None:
        self._root: Path | None = None

    def setup(self, repo_root: Path) -> None:
        self._root = Path(repo_root)

    def teardown(self) -> None:
        self._root = None

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="grep",
                description=(
                    "Search every source file with a regular expression."
                    " Returns matching lines as path:line: text."
                ),
                parameters={"pattern": "regular expression to search for"},
            )
        ]

    def call(self, tool: str, arguments: dict) -> str:
        assert self._root is not None, "setup() was not called"
        if tool != "grep":
            return f"unknown tool {tool!r}"
        try:
            pattern = re.compile(arguments["pattern"])
        except re.error as error:
            return f"invalid pattern: {error}"
        hits: list[str] = []
        for path in indexer.iter_source_files(self._root):
            relative = path.relative_to(self._root).as_posix()
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    hits.append(f"{relative}:{line_number}: {line.strip()[:160]}")
                    if len(hits) >= _MAX_GREP_RESULTS:
                        hits.append(f"[truncated at {_MAX_GREP_RESULTS} matches]")
                        return "\n".join(hits)
        return "\n".join(hits) if hits else "no matches"


class CidxAdapter:
    """cidx as a contestant: the five read-only tools, via the library."""

    name = "cidx"

    def __init__(self) -> None:
        self._root: Path | None = None
        self._tempdir: tempfile.TemporaryDirectory | None = None
        self._store: Store | None = None

    def setup(self, repo_root: Path) -> None:
        self._root = Path(repo_root)
        self._tempdir = tempfile.TemporaryDirectory(prefix="cidx-bench-")
        self._store = Store.open(Path(self._tempdir.name) / "index.db")
        indexer.index_repository(self._root, self._store)

    def teardown(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None
        if self._tempdir is not None:
            self._tempdir.cleanup()
            self._tempdir = None

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="search_symbols",
                description="Fuzzy-search symbols by name; ranked results.",
                parameters={"query": "symbol name or fragment"},
            ),
            ToolSpec(
                name="find_definition",
                description="Exact definition lookup by name or qualified name.",
                parameters={"name": "symbol name, e.g. Repo.save"},
            ),
            ToolSpec(
                name="find_references",
                description="Usage sites of a symbol, with confidence tags.",
                parameters={"name": "symbol name"},
            ),
            ToolSpec(
                name="outline_file",
                description="Every symbol one file defines, in order.",
                parameters={"path": "repo-relative path"},
            ),
            ToolSpec(
                name="repo_map",
                description="Ranked overview: popular files and their symbols.",
                parameters={},
            ),
        ]

    def call(self, tool: str, arguments: dict) -> str:
        store = self._store
        assert store is not None, "setup() was not called"
        if tool == "search_symbols":
            rows, total = scorer.search_symbols(store, arguments["query"], limit=50)
            lines = [_row_line(r) for r in rows]
            return budget.shape(lines, total, store).render()
        if tool == "find_definition":
            rows = query_layer.find_definition(store, arguments["name"])
            if not rows:
                return budget.fail_open_message(
                    f"no definition of {arguments['name']!r}"
                )
            return budget.shape([_row_line(r) for r in rows], len(rows), store).render()
        if tool == "find_references":
            refs = query_layer.find_references(store, arguments["name"])
            lines = [f"{r.path}:{r.line}  {r.name}  [{r.confidence}]" for r in refs]
            return budget.shape(lines, len(refs), store).render()
        if tool == "outline_file":
            rows = query_layer.outline_file(store, arguments["path"])
            lines = [f"{r.start_line}  {r.qualified_name}  {r.kind}" for r in rows]
            return budget.shape(lines, len(rows), store).render()
        if tool == "repo_map":
            entries = query_layer.repo_map(store)
            lines = [
                f"{e.path}  ({e.symbol_count} symbols, {e.incoming_refs} inbound)"
                for e in entries
            ]
            return budget.shape(lines, len(entries), store).render()
        return f"unknown tool {tool!r}"


def _row_line(row) -> str:
    line = f"{row.qualified_name}  {row.kind}  {row.path}:{row.start_line}"
    if row.signature:
        line += f"  {row.signature}"
    return line
