"""Reference resolution: the cascade, computed over the whole index.

The cascade (ARCHITECTURE.md): same-file scope, then explicit imports
followed to their source (one hop), then unique global name, else unresolved.
Confidence tags: ``exact`` (same file), ``import`` (via an import), and
``name-only`` (global-unique match, or unresolved with NULL target).

Resolution is a deterministic function of whole-repository state and is
recomputed after mutations, so an incrementally maintained index and a cold
rebuild always agree — the convergence snapshot includes resolved targets.
There is deliberately no type checker; precision per tier is measured by the
benchmark, not promised.
"""

from __future__ import annotations

import posixpath
import sqlite3
from dataclasses import dataclass

_DEFINITION_KINDS = ("function", "class", "method", "const")

_JS_LANGUAGES = frozenset({"javascript", "typescript", "tsx"})
_JS_SUFFIXES = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    "/index.ts",
    "/index.tsx",
    "/index.js",
    "/index.jsx",
)


@dataclass(frozen=True, slots=True)
class _Def:
    id: int
    file_id: int
    path: str
    name: str
    start_line: int
    end_line: int


def resolve_all(connection: sqlite3.Connection) -> None:
    """Recompute resolved_symbol_id and confidence for every reference.

    The caller manages the transaction.
    """
    placeholders = ", ".join("?" for _ in _DEFINITION_KINDS)
    defs: list[_Def] = [
        _Def(*row)
        for row in connection.execute(
            "SELECT s.id, s.file_id, f.path, s.name, s.start_line, s.end_line"
            " FROM symbols s JOIN files f ON f.id = s.file_id"
            f" WHERE s.kind IN ({placeholders})",
            _DEFINITION_KINDS,
        )
    ]
    defs_by_file: dict[tuple[int, str], list[_Def]] = {}
    defs_by_name: dict[str, list[_Def]] = {}
    defs_by_path_name: dict[tuple[str, str], list[_Def]] = {}
    for definition in defs:
        defs_by_file.setdefault((definition.file_id, definition.name), []).append(
            definition
        )
        defs_by_name.setdefault(definition.name, []).append(definition)
        defs_by_path_name.setdefault((definition.path, definition.name), []).append(
            definition
        )

    imports: dict[tuple[int, str], tuple[str, str, str]] = {}
    for row in connection.execute(
        "SELECT s.file_id, s.name, s.signature, f.language, f.path"
        " FROM symbols s JOIN files f ON f.id = s.file_id"
        " WHERE s.kind = 'import' AND s.signature IS NOT NULL"
    ):
        imports.setdefault((row[0], row[1]), (row[2], row[3], row[4]))

    updates: list[tuple[int | None, str, int]] = []
    for ref_id, file_id, name, line in connection.execute(
        "SELECT id, file_id, name, line FROM refs"
    ):
        resolved, confidence = _resolve_one(
            file_id, name, line, defs_by_file, defs_by_name, defs_by_path_name, imports
        )
        updates.append((resolved, confidence, ref_id))
    connection.executemany(
        "UPDATE refs SET resolved_symbol_id = ?, confidence = ? WHERE id = ?",
        updates,
    )


def _resolve_one(
    file_id: int,
    name: str,
    line: int,
    defs_by_file: dict[tuple[int, str], list[_Def]],
    defs_by_name: dict[str, list[_Def]],
    defs_by_path_name: dict[tuple[str, str], list[_Def]],
    imports: dict[tuple[int, str], tuple[str, str, str]],
) -> tuple[int | None, str]:
    same_file = defs_by_file.get((file_id, name))
    if same_file:
        return _pick(same_file, line).id, "exact"

    imported = imports.get((file_id, name))
    if imported is not None:
        target, language, importing_path = imported
        for candidate_path, symbol_name in _import_candidates(
            target, language, importing_path
        ):
            found = defs_by_path_name.get((candidate_path, symbol_name))
            if found:
                return _pick(found, line=None).id, "import"

    global_defs = defs_by_name.get(name, [])
    if len(global_defs) == 1:
        return global_defs[0].id, "name-only"
    return None, "name-only"


def _pick(candidates: list[_Def], line: int | None) -> _Def:
    """Deterministic choice among same-name candidates.

    Prefer the innermost definition enclosing the reference line (a recursive
    call resolves to its own function); otherwise the earliest definition.
    Ties break on values, never on database ids.
    """
    if line is not None:
        enclosing = [d for d in candidates if d.start_line <= line <= d.end_line]
        if enclosing:
            return max(enclosing, key=lambda d: (d.start_line, d.path))
    return min(candidates, key=lambda d: (d.start_line, d.path))


def _import_candidates(
    target: str, language: str, importing_path: str
) -> list[tuple[str, str]]:
    """(file path, symbol name) pairs an import breadcrumb may point at."""
    if language in _JS_LANGUAGES:
        return _js_candidates(target, importing_path)
    return _python_candidates(target, importing_path)


def _python_candidates(target: str, importing_path: str) -> list[tuple[str, str]]:
    dots = len(target) - len(target.lstrip("."))
    rest = target.lstrip(".")
    parts = rest.split(".") if rest else []
    if len(parts) < 1 or (dots == 0 and len(parts) < 2):
        return []  # a bare module import binds no followable symbol
    prefix: list[str] = []
    if dots:
        base = posixpath.dirname(importing_path)
        for _ in range(dots - 1):
            base = posixpath.dirname(base)
        prefix = [p for p in base.split("/") if p]
    *module_parts, symbol_name = parts
    module = "/".join(prefix + module_parts)
    candidates = []
    if module:
        candidates.append((f"{module}.py", symbol_name))
        candidates.append((f"{module}/__init__.py", symbol_name))
    else:
        candidates.append(("__init__.py", symbol_name))
    return candidates


def _js_candidates(target: str, importing_path: str) -> list[tuple[str, str]]:
    module, _, symbol_name = target.rpartition(":")
    if not module or symbol_name == "*":
        return []
    if not module.startswith("."):
        return []  # bare specifiers live in node_modules, outside the index
    base = posixpath.normpath(posixpath.join(posixpath.dirname(importing_path), module))
    return [(base + suffix, symbol_name) for suffix in _JS_SUFFIXES]
