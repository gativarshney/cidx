; Extraction anchors for Python. Patterns capture the nodes that matter;
; ancestry-dependent facts (qualified names, method vs function, scope
; filtering) are computed in python.py, because queries cannot see ancestors.

; --- Definitions -------------------------------------------------------------

(function_definition name: (identifier) @function.def)

(class_definition name: (identifier) @class.def)

; Module- and class-level bindings, including annotated ones (x: int = 1).
; Bindings inside functions are locals and get filtered out in python.py.
(expression_statement (assignment left: (identifier) @const.def))

(import_statement) @import.stmt
(import_from_statement) @import.stmt

; --- Raw references ----------------------------------------------------------
; Deliberately usage-proven positions only: call sites, decorators, and base
; classes. Bare identifier loads are too noisy to index in v1.

(call function: (identifier) @ref)
(call function: (attribute attribute: (identifier) @ref))

; @deco and @mod.deco; @deco(...) forms are already matched by the call
; patterns above, so they are not repeated here.
(decorator (identifier) @ref)
(decorator (attribute attribute: (identifier) @ref))

(class_definition superclasses: (argument_list (identifier) @ref))
(class_definition superclasses: (argument_list (attribute attribute: (identifier) @ref)))
