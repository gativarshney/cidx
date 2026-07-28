"""Language registry and error-tolerant parsing on top of tree-sitter.

Extractors build on this module: it maps file paths to supported language ids
and produces parse trees from raw bytes. Sources are always parsed as bytes;
decoding for display is the caller's concern (see ARCHITECTURE.md).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import PurePath
from typing import Literal

import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser, Query, Tree

PYTHON = "python"
JAVASCRIPT = "javascript"
TYPESCRIPT = "typescript"
TSX = "tsx"

#: Language ids as stored in the index's files.language column.
SUPPORTED_LANGUAGES: frozenset[str] = frozenset({PYTHON, JAVASCRIPT, TYPESCRIPT, TSX})

_LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": PYTHON,
    ".pyi": PYTHON,
    ".js": JAVASCRIPT,
    ".jsx": JAVASCRIPT,
    ".mjs": JAVASCRIPT,
    ".cjs": JAVASCRIPT,
    ".ts": TYPESCRIPT,
    ".mts": TYPESCRIPT,
    ".cts": TYPESCRIPT,
    ".tsx": TSX,
}

_LANGUAGE_LOADERS: dict[str, Callable[[], object]] = {
    PYTHON: tree_sitter_python.language,
    JAVASCRIPT: tree_sitter_javascript.language,
    TYPESCRIPT: tree_sitter_typescript.language_typescript,
    TSX: tree_sitter_typescript.language_tsx,
}


def detect_language(path: str | PurePath) -> str | None:
    """Return the language id for *path*, or None if cidx does not index it."""
    return _LANGUAGE_BY_EXTENSION.get(PurePath(path).suffix.lower())


@cache
def get_language(language_id: str) -> Language:
    """Return the compiled tree-sitter grammar for *language_id*.

    Raises ValueError for ids outside SUPPORTED_LANGUAGES.
    """
    try:
        loader = _LANGUAGE_LOADERS[language_id]
    except KeyError:
        supported = ", ".join(sorted(SUPPORTED_LANGUAGES))
        raise ValueError(
            f"unsupported language {language_id!r}; use one of: {supported}"
        ) from None
    return Language(loader())


@cache
def get_parser(language_id: str) -> Parser:
    """Return the shared, reusable parser for *language_id*."""
    return Parser(get_language(language_id))


def parse(source: bytes, language_id: str) -> Tree:
    """Parse *source* into a syntax tree.

    Error-tolerant by construction: broken or half-written code still yields a
    tree (with error nodes), never an exception.
    """
    return get_parser(language_id).parse(source)


SymbolKind = Literal["function", "class", "method", "const", "import"]


@dataclass(frozen=True, slots=True)
class Symbol:
    """One definition emitted by an extractor.

    Line numbers are 1-based and inclusive. ``parent`` is the qualified name
    of the enclosing definition, or None at module level. For imports,
    ``signature`` carries the dotted import target (the resolution breadcrumb
    used in Phase 6).
    """

    name: str
    qualified_name: str
    kind: SymbolKind
    start_line: int
    end_line: int
    signature: str | None = None
    parent: str | None = None


@dataclass(frozen=True, slots=True)
class Reference:
    """One raw symbol usage at a 1-based line; resolution happens at Phase 6."""

    name: str
    line: int


@dataclass(frozen=True, slots=True)
class Extraction:
    """Everything one extractor emits for one file."""

    symbols: tuple[Symbol, ...]
    references: tuple[Reference, ...]


def node_text(source: bytes, node: Node) -> str:
    """Decode the exact source slice *node* spans (UTF-8, lossy on bad bytes)."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def load_query(language_id: str, *filenames: str) -> Query:
    """Compile ``.scm`` query files shipped in ``cidx/extractors/queries``.

    Multiple filenames are concatenated, so grammar variants can share a core
    pattern file (TSX = TypeScript core + JSX additions).
    """
    query_dir = resources.files("cidx.extractors") / "queries"
    text = "\n".join(
        (query_dir / filename).read_text(encoding="utf-8") for filename in filenames
    )
    return Query(get_language(language_id), text)
