"""Symbol and raw-reference extraction for Python sources.

Contract:

- Symbols are module- and class-level definitions: functions, classes,
  methods (functions whose nearest enclosing definition is a class), consts
  (assignments, including annotated ones), and imports. Locals and
  function-scoped imports are not symbols.
- Qualified names join enclosing definition names with dots (``Repo.save``).
- References are usage-proven positions only: call sites, decorator names,
  and base classes. Resolution to definitions happens at query time (Phase 6).
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import cache

from tree_sitter import Node, Query, QueryCursor

from cidx.extractors import base
from cidx.extractors.base import Extraction, Reference, Symbol

_DEFINITION_TYPES = frozenset({"function_definition", "class_definition"})


@cache
def _query() -> Query:
    return base.load_query(base.PYTHON, "python.scm")


def extract(source: bytes) -> Extraction:
    """Extract symbols and raw references from Python source bytes.

    Never raises on broken code: whatever tree-sitter recovers is extracted.
    """
    tree = base.parse(source, base.PYTHON)
    captures = QueryCursor(_query()).captures(tree.root_node)

    symbols: list[Symbol] = []
    for node in captures.get("function.def", []):
        symbols.append(_definition_symbol(source, node, class_kind=False))
    for node in captures.get("class.def", []):
        symbols.append(_definition_symbol(source, node, class_kind=True))
    for node in captures.get("const.def", []):
        const = _const_symbol(source, node)
        if const is not None:
            symbols.append(const)
    for stmt in captures.get("import.stmt", []):
        symbols.extend(_import_symbols(source, stmt))
    # Sort before deduping so "first binding" means lowest line, not
    # whichever capture the query cursor happened to yield first.
    symbols.sort(key=lambda s: (s.start_line, s.qualified_name))
    symbols = _dedupe_consts(symbols)

    seen: set[tuple[str, int]] = set()
    references: list[Reference] = []
    for node in captures.get("ref", []):
        ref = Reference(
            name=base.node_text(source, node), line=node.start_point.row + 1
        )
        if (ref.name, ref.line) not in seen:
            seen.add((ref.name, ref.line))
            references.append(ref)
    references.sort(key=lambda r: (r.line, r.name))

    return Extraction(symbols=tuple(symbols), references=tuple(references))


def _definition_symbol(source: bytes, name_node: Node, *, class_kind: bool) -> Symbol:
    defn = name_node.parent
    assert defn is not None  # query guarantees a definition parent
    scope = _scope_names(source, defn)
    name = base.node_text(source, name_node)
    if class_kind:
        kind: base.SymbolKind = "class"
    else:
        kind = "method" if _nearest_definition_is_class(defn) else "function"
    return Symbol(
        name=name,
        qualified_name=_join(scope, name),
        kind=kind,
        start_line=defn.start_point.row + 1,
        end_line=defn.end_point.row + 1,
        signature=_signature(source, defn),
        parent=".".join(scope) or None,
    )


def _const_symbol(source: bytes, name_node: Node) -> Symbol | None:
    assignment = name_node.parent
    assert assignment is not None
    if _has_function_ancestor(assignment):
        return None  # local variable, not a symbol
    scope = _scope_names(source, assignment)
    name = base.node_text(source, name_node)
    return Symbol(
        name=name,
        qualified_name=_join(scope, name),
        kind="const",
        start_line=assignment.start_point.row + 1,
        end_line=assignment.end_point.row + 1,
        parent=".".join(scope) or None,
    )


def _import_symbols(source: bytes, stmt: Node) -> Iterator[Symbol]:
    if _has_function_ancestor(stmt):
        return  # function-scoped import: a local binding
    scope = _scope_names(source, stmt)
    start = stmt.start_point.row + 1
    end = stmt.end_point.row + 1

    def make(local_name: str, target: str) -> Symbol:
        return Symbol(
            name=local_name,
            qualified_name=_join(scope, local_name),
            kind="import",
            start_line=start,
            end_line=end,
            signature=target,
            parent=".".join(scope) or None,
        )

    if stmt.type == "import_statement":
        for child in stmt.named_children:
            if child.type == "dotted_name":
                dotted = base.node_text(source, child)
                yield make(dotted, dotted)
            elif child.type == "aliased_import":
                yield make(
                    _field_text(source, child, "alias"),
                    _field_text(source, child, "name"),
                )
        return

    # import_from_statement; wildcard imports bind no name and are skipped.
    module_node = stmt.child_by_field_name("module_name")
    module = base.node_text(source, module_node) if module_node is not None else ""
    for child in stmt.named_children:
        if module_node is not None and child.id == module_node.id:
            continue
        if child.type == "dotted_name":
            imported = base.node_text(source, child)
            yield make(imported, _dotted(module, imported))
        elif child.type == "aliased_import":
            yield make(
                _field_text(source, child, "alias"),
                _dotted(module, _field_text(source, child, "name")),
            )


def _dedupe_consts(symbols: list[Symbol]) -> list[Symbol]:
    """Keep only the first binding when a const is reassigned in one file."""
    seen: set[str] = set()
    kept: list[Symbol] = []
    for symbol in symbols:
        if symbol.kind == "const":
            if symbol.qualified_name in seen:
                continue
            seen.add(symbol.qualified_name)
        kept.append(symbol)
    return kept


def _scope_names(source: bytes, node: Node) -> list[str]:
    """Names of the definitions enclosing *node*, outermost first."""
    names: list[str] = []
    current = node.parent
    while current is not None:
        if current.type in _DEFINITION_TYPES:
            name_node = current.child_by_field_name("name")
            if name_node is not None:
                names.append(base.node_text(source, name_node))
        current = current.parent
    names.reverse()
    return names


def _nearest_definition_is_class(defn: Node) -> bool:
    current = defn.parent
    while current is not None:
        if current.type in _DEFINITION_TYPES:
            return current.type == "class_definition"
        current = current.parent
    return False


def _has_function_ancestor(node: Node) -> bool:
    current = node.parent
    while current is not None:
        if current.type == "function_definition":
            return True
        current = current.parent
    return False


def _signature(source: bytes, defn: Node) -> str | None:
    """The definition header (through the return annotation), on one line."""
    body = defn.child_by_field_name("body")
    end_byte = body.start_byte if body is not None else defn.end_byte
    raw = source[defn.start_byte : end_byte].decode("utf-8", errors="replace")
    return " ".join(raw.split()).rstrip(":") or None


def _join(scope: list[str], name: str) -> str:
    return ".".join([*scope, name])


def _dotted(module: str, name: str) -> str:
    if not module:
        return name
    if module.endswith("."):
        return module + name  # relative import: "." + "x" -> ".x"
    return f"{module}.{name}"


def _field_text(source: bytes, node: Node, field: str) -> str:
    child = node.child_by_field_name(field)
    assert child is not None  # grammar guarantees these fields
    return base.node_text(source, child)
