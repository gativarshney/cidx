; Extraction anchors for the JavaScript grammar (which includes JSX).
; Mirrors typescript.scm; differences are grammar-level: class names are plain
; identifiers, fields use the `property` field, and heritage is class_heritage
; rather than extends/implements clauses.

; --- Definitions -------------------------------------------------------------

(function_declaration name: (identifier) @function.def)
(generator_function_declaration name: (identifier) @function.def)

(class_declaration name: (identifier) @class.def)

(method_definition name: (property_identifier) @method.def)

(variable_declarator name: (identifier) @var.def)

(field_definition property: (property_identifier) @field.def)

(import_statement) @import.stmt
(export_statement) @export.stmt

; --- Raw references ----------------------------------------------------------

(call_expression function: (identifier) @ref)
(call_expression function: (member_expression property: (property_identifier) @ref))

(new_expression constructor: (identifier) @ref)
(new_expression constructor: (member_expression property: (property_identifier) @ref))

(decorator (identifier) @ref)
(decorator (member_expression property: (property_identifier) @ref))

(class_heritage (identifier) @ref)
(class_heritage (member_expression property: (property_identifier) @ref))

; JSX component usages (uppercase = component; lowercase intrinsics skipped).
(jsx_opening_element name: (identifier) @ref (#match? @ref "^[A-Z]"))
(jsx_self_closing_element name: (identifier) @ref (#match? @ref "^[A-Z]"))
(jsx_opening_element name: (member_expression property: (property_identifier) @ref (#match? @ref "^[A-Z]")))
(jsx_self_closing_element name: (member_expression property: (property_identifier) @ref (#match? @ref "^[A-Z]")))
