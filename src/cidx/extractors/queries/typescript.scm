; Extraction anchors for the TypeScript grammar (shared by TSX; JSX patterns
; live in tsx.scm). Ancestry-dependent facts are computed in typescript.py.

; --- Definitions -------------------------------------------------------------

(function_declaration name: (identifier) @function.def)
(generator_function_declaration name: (identifier) @function.def)

(class_declaration name: (type_identifier) @class.def)

(method_definition name: (property_identifier) @method.def)

; Captures every declarator; typescript.py keeps module/class-level bindings
; (consts) and function-valued bindings (arrow functions on consts).
(variable_declarator name: (identifier) @var.def)

(public_field_definition name: (property_identifier) @field.def)

(import_statement) @import.stmt
(export_statement) @export.stmt

; --- Raw references ----------------------------------------------------------
; Usage-proven positions only: calls, constructions, decorators, heritage.

(call_expression function: (identifier) @ref)
(call_expression function: (member_expression property: (property_identifier) @ref))

(new_expression constructor: (identifier) @ref)
(new_expression constructor: (member_expression property: (property_identifier) @ref))

; @deco and @ns.deco; @deco(...) is already matched by the call patterns.
(decorator (identifier) @ref)
(decorator (member_expression property: (property_identifier) @ref))

(extends_clause (identifier) @ref)
(extends_clause (member_expression property: (property_identifier) @ref))
(implements_clause (type_identifier) @ref)
