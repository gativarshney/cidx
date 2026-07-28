"""Symbol and raw-reference extraction for JavaScript, TypeScript, and TSX.

Contract (mirrors the Python extractor where the languages align):

- Symbols: functions (declarations, and arrow/function expressions bound to a
  variable), classes, methods, class fields (function-valued fields are
  methods, others are consts), module/class-level consts, and imports. Plain
  consts inside functions are locals and excluded; nested function bindings
  are kept, matching Python's nested ``def`` behavior.
- Anonymous default exports emit a symbol named ``default``; ``export default
  someIdentifier`` emits a reference instead. Re-exports (``export { x } from
  'mod'``) emit import symbols; ``export * from`` emits nothing.
- Import signatures carry ``<module>:<exported-name>`` breadcrumbs, with
  ``default`` and ``*`` for default and namespace imports.
- References: calls, ``new`` constructions, decorators, heritage clauses, and
  uppercase JSX component usages. Bare identifier loads are not indexed.
- CommonJS (``module.exports``, ``require``) binds no symbols beyond the
  assigned const; ``require(...)`` shows up as a call reference.
"""

from __future__ import annotations

from functools import cache

from tree_sitter import Node, Query, QueryCursor

from cidx.extractors import base
from cidx.extractors.base import Extraction, Reference, Symbol

_FUNCTION_SCOPES = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "function_expression",
        "generator_function",
        "arrow_function",
        "method_definition",
    }
)
_VALUE_FUNCTIONS = frozenset(
    {"arrow_function", "function_expression", "generator_function"}
)
_CLASS_TYPES = frozenset({"class_declaration", "class"})
_FIELD_TYPES = frozenset({"public_field_definition", "field_definition"})


@cache
def _query(language_id: str) -> Query:
    if language_id == base.JAVASCRIPT:
        return base.load_query(language_id, "javascript.scm")
    if language_id == base.TYPESCRIPT:
        return base.load_query(language_id, "typescript.scm")
    if language_id == base.TSX:
        return base.load_query(language_id, "typescript.scm", "tsx.scm")
    supported = ", ".join((base.JAVASCRIPT, base.TYPESCRIPT, base.TSX))
    raise ValueError(f"unsupported language {language_id!r}; use one of: {supported}")


def extract(source: bytes, language_id: str) -> Extraction:
    """Extract symbols and raw references from JS/TS/TSX source bytes.

    Never raises on broken code: whatever tree-sitter recovers is extracted.
    """
    captures = QueryCursor(_query(language_id)).captures(
        base.parse(source, language_id).root_node
    )

    symbols: list[Symbol] = []
    references: list[Reference] = []
    for node in captures.get("function.def", []):
        symbols.append(_declaration_symbol(source, node, kind="function"))
    for node in captures.get("class.def", []):
        symbols.append(_declaration_symbol(source, node, kind="class"))
    for node in captures.get("method.def", []):
        symbols.append(_declaration_symbol(source, node, kind="method"))
    for node in captures.get("var.def", []):
        variable = _variable_symbol(source, node)
        if variable is not None:
            symbols.append(variable)
    for node in captures.get("field.def", []):
        symbols.append(_field_symbol(source, node))
    for stmt in captures.get("import.stmt", []):
        symbols.extend(_import_symbols(source, stmt))
    for stmt in captures.get("export.stmt", []):
        export_symbols, export_refs = _export_extras(source, stmt)
        symbols.extend(export_symbols)
        references.extend(export_refs)
    symbols.sort(key=lambda s: (s.start_line, s.qualified_name))

    for node in captures.get("ref", []):
        references.append(
            Reference(name=base.node_text(source, node), line=node.start_point.row + 1)
        )
    seen: set[tuple[str, int]] = set()
    deduped: list[Reference] = []
    for ref in references:
        if (ref.name, ref.line) not in seen:
            seen.add((ref.name, ref.line))
            deduped.append(ref)
    deduped.sort(key=lambda r: (r.line, r.name))

    return Extraction(symbols=tuple(symbols), references=tuple(deduped))


def _declaration_symbol(source: bytes, name_node: Node, *, kind: str) -> Symbol:
    defn = name_node.parent
    assert defn is not None  # query guarantees a definition parent
    scope = _scope_names(source, defn)
    name = base.node_text(source, name_node)
    start_byte, start_line = _after_decorators(defn)
    body = defn.child_by_field_name("body")
    sig_end = body.start_byte if body is not None else defn.end_byte
    return Symbol(
        name=name,
        qualified_name=_join(scope, name),
        kind=kind,  # type: ignore[arg-type]
        start_line=start_line,
        end_line=defn.end_point.row + 1,
        signature=_collapse(source[start_byte:sig_end]),
        parent=".".join(scope) or None,
    )


def _variable_symbol(source: bytes, name_node: Node) -> Symbol | None:
    declarator = name_node.parent
    assert declarator is not None
    value = declarator.child_by_field_name("value")
    is_function = value is not None and value.type in _VALUE_FUNCTIONS
    if not is_function and _has_function_ancestor(declarator):
        return None  # local variable, not a symbol
    scope = _scope_names(source, declarator)
    name = base.node_text(source, name_node)
    if is_function:
        assert value is not None
        declaration = declarator.parent  # lexical_declaration carries `const`
        start = declaration if declaration is not None else declarator
        return Symbol(
            name=name,
            qualified_name=_join(scope, name),
            kind="function",
            start_line=start.start_point.row + 1,
            end_line=declarator.end_point.row + 1,
            signature=_collapse(source[start.start_byte : _body_start(value)]),
            parent=".".join(scope) or None,
        )
    return Symbol(
        name=name,
        qualified_name=_join(scope, name),
        kind="const",
        start_line=declarator.start_point.row + 1,
        end_line=declarator.end_point.row + 1,
        parent=".".join(scope) or None,
    )


def _field_symbol(source: bytes, name_node: Node) -> Symbol:
    field = name_node.parent
    assert field is not None
    value = field.child_by_field_name("value")
    is_function = value is not None and value.type in _VALUE_FUNCTIONS
    scope = _scope_names(source, field)
    name = base.node_text(source, name_node)
    start_byte, start_line = _after_decorators(field)
    signature = None
    if is_function:
        assert value is not None
        signature = _collapse(source[start_byte : _body_start(value)])
    return Symbol(
        name=name,
        qualified_name=_join(scope, name),
        kind="method" if is_function else "const",
        start_line=start_line,
        end_line=field.end_point.row + 1,
        signature=signature,
        parent=".".join(scope) or None,
    )


def _import_symbols(source: bytes, stmt: Node) -> list[Symbol]:
    if _has_function_ancestor(stmt):
        return []
    source_node = stmt.child_by_field_name("source")
    module = _module_text(source, source_node)
    start = stmt.start_point.row + 1
    end = stmt.end_point.row + 1

    def make(local_name: str, target: str) -> Symbol:
        return Symbol(
            name=local_name,
            qualified_name=local_name,
            kind="import",
            start_line=start,
            end_line=end,
            signature=f"{module}:{target}",
        )

    symbols: list[Symbol] = []
    clause = next((c for c in stmt.named_children if c.type == "import_clause"), None)
    if clause is None:
        return symbols  # side-effect import binds nothing
    for child in clause.named_children:
        if child.type == "identifier":
            symbols.append(make(base.node_text(source, child), "default"))
        elif child.type == "namespace_import":
            for inner in child.named_children:
                if inner.type == "identifier":
                    symbols.append(make(base.node_text(source, inner), "*"))
        elif child.type == "named_imports":
            for spec in child.named_children:
                if spec.type != "import_specifier":
                    continue
                exported = _field_text(source, spec, "name")
                alias_node = spec.child_by_field_name("alias")
                local = (
                    base.node_text(source, alias_node)
                    if alias_node is not None
                    else exported
                )
                symbols.append(make(local, exported))
    return symbols


def _export_extras(source: bytes, stmt: Node) -> tuple[list[Symbol], list[Reference]]:
    """Re-exports, anonymous default exports, and exported-name references.

    Exported declarations (``export function f`` and friends) are already
    captured by the definition patterns and are not handled here.
    """
    symbols: list[Symbol] = []
    references: list[Reference] = []
    if _has_function_ancestor(stmt):
        return symbols, references

    clause = next((c for c in stmt.named_children if c.type == "export_clause"), None)
    if clause is not None:
        source_node = stmt.child_by_field_name("source")
        if source_node is not None:  # export { a, b as c } from './mod'
            module = _module_text(source, source_node)
            for spec in clause.named_children:
                if spec.type != "export_specifier":
                    continue
                exported = _field_text(source, spec, "name")
                alias_node = spec.child_by_field_name("alias")
                local = (
                    base.node_text(source, alias_node)
                    if alias_node is not None
                    else exported
                )
                symbols.append(
                    Symbol(
                        name=local,
                        qualified_name=local,
                        kind="import",
                        start_line=stmt.start_point.row + 1,
                        end_line=stmt.end_point.row + 1,
                        signature=f"{module}:{exported}",
                    )
                )
        else:  # export { a, b }: usages of local symbols
            for spec in clause.named_children:
                if spec.type != "export_specifier":
                    continue
                name_node = spec.child_by_field_name("name")
                if name_node is not None and name_node.type == "identifier":
                    references.append(
                        Reference(
                            name=base.node_text(source, name_node),
                            line=name_node.start_point.row + 1,
                        )
                    )
        return symbols, references

    if not any(child.type == "default" for child in stmt.children):
        return symbols, references
    value = next((c for c in stmt.named_children if c.type != "decorator"), None)
    if value is None or value.type in {"function_declaration", "class_declaration"}:
        return symbols, references  # named declaration: captured by patterns
    if value.type in _VALUE_FUNCTIONS or value.type == "class":
        name_node = value.child_by_field_name("name")
        name = base.node_text(source, name_node) if name_node is not None else "default"
        body = value.child_by_field_name("body")
        sig_end = body.start_byte if body is not None else value.end_byte
        symbols.append(
            Symbol(
                name=name,
                qualified_name=name,
                kind="class" if value.type == "class" else "function",
                start_line=value.start_point.row + 1,
                end_line=value.end_point.row + 1,
                signature=_collapse(source[value.start_byte : sig_end]),
            )
        )
    elif value.type == "identifier":  # export default myThing
        references.append(
            Reference(
                name=base.node_text(source, value),
                line=value.start_point.row + 1,
            )
        )
    return symbols, references


def _scope_names(source: bytes, node: Node) -> list[str]:
    """Names of the definitions enclosing *node*, outermost first."""
    names: list[str] = []
    current = node.parent
    while current is not None:
        contribution = _scope_contribution(source, current)
        if contribution is not None:
            names.append(contribution)
        current = current.parent
    names.reverse()
    return names


def _scope_contribution(source: bytes, node: Node) -> str | None:
    if node.type in _CLASS_TYPES:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return base.node_text(source, name_node)
        return _binding_name(source, node) or "default"
    if node.type in {"function_declaration", "generator_function_declaration"}:
        name_node = node.child_by_field_name("name")
        return base.node_text(source, name_node) if name_node is not None else None
    if node.type == "method_definition":
        name_node = node.child_by_field_name("name")
        return base.node_text(source, name_node) if name_node is not None else None
    if node.type in _VALUE_FUNCTIONS:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return base.node_text(source, name_node)
        return _binding_name(source, node)
    return None


def _binding_name(source: bytes, value_node: Node) -> str | None:
    """The variable or field name a function/class expression is bound to."""
    parent = value_node.parent
    if parent is None:
        return None
    if parent.type == "variable_declarator":
        name_node = parent.child_by_field_name("name")
        if name_node is not None and name_node.type == "identifier":
            return base.node_text(source, name_node)
    if parent.type in _FIELD_TYPES:
        name_node = _field_name_node(parent)
        if name_node is not None:
            return base.node_text(source, name_node)
    return None


def _field_name_node(field: Node) -> Node | None:
    # TS grammar calls the field `name`; JS grammar calls it `property`.
    return field.child_by_field_name("name") or field.child_by_field_name("property")


def _has_function_ancestor(node: Node) -> bool:
    current = node.parent
    while current is not None:
        if current.type in _FUNCTION_SCOPES:
            return True
        current = current.parent
    return False


def _after_decorators(defn: Node) -> tuple[int, int]:
    """Start byte and 1-based line of *defn*, skipping leading decorators."""
    for child in defn.children:
        if child.type != "decorator":
            return child.start_byte, child.start_point.row + 1
    return defn.start_byte, defn.start_point.row + 1


def _body_start(value_node: Node) -> int:
    body = value_node.child_by_field_name("body")
    return body.start_byte if body is not None else value_node.end_byte


def _module_text(source: bytes, string_node: Node | None) -> str:
    if string_node is None:
        return ""
    for child in string_node.named_children:
        if child.type == "string_fragment":
            return base.node_text(source, child)
    return ""


def _collapse(raw: bytes) -> str | None:
    text = " ".join(raw.decode("utf-8", errors="replace").split())
    return text or None


def _join(scope: list[str], name: str) -> str:
    return ".".join([*scope, name])


def _field_text(source: bytes, node: Node, field: str) -> str:
    child = node.child_by_field_name(field)
    assert child is not None  # grammar guarantees these fields
    return base.node_text(source, child)
