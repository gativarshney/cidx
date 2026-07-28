; JSX additions for the TSX grammar, appended to typescript.scm.
; Uppercase names are components (usages worth indexing); lowercase names are
; intrinsic elements like <div> and are skipped.

(jsx_opening_element name: (identifier) @ref (#match? @ref "^[A-Z]"))
(jsx_self_closing_element name: (identifier) @ref (#match? @ref "^[A-Z]"))
(jsx_opening_element name: (member_expression property: (property_identifier) @ref (#match? @ref "^[A-Z]")))
(jsx_self_closing_element name: (member_expression property: (property_identifier) @ref (#match? @ref "^[A-Z]")))
