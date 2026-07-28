"""Language registry and error-tolerant parsing on top of tree-sitter.

Extractors build on this module: it maps file paths to supported language ids
and produces parse trees from raw bytes. Sources are always parsed as bytes;
decoding for display is the caller's concern (see ARCHITECTURE.md).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from pathlib import PurePath

import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Parser, Tree

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
