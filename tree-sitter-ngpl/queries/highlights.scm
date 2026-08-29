; Highlighting for NGPL.
;
; The glyphs an operator is written with are what a reader looks for
; first, so every one of them is marked, and the measures with them:
; a unit is what tells one count from another and is worth seeing.

; -- what a file declares -------------------------------------------

(function_definition name: (identifier) @function)
(nested_function name: (identifier) @function)
(struct_definition name: (identifier) @type)
(enum_definition name: (identifier) @type)
(type_alias name: (identifier) @type)
(unit_definition name: (identifier) @type.definition)
(impl_block type: (identifier) @type)
(module_definition name: (identifier) @namespace)

(parameter name: (identifier) @variable.parameter)
(lambda_parameter name: (identifier) @variable.parameter)
(field_declaration name: (identifier) @property)
(enumerator name: (identifier) @constant)

; -- what a name stands for ------------------------------------------

(call_expression function: (identifier) @function.call)
(call_expression function: (field_expression field: (identifier) @function.method))
(field_expression field: (identifier) @property)
(struct_literal name: (identifier) @type)
(struct_literal field: (identifier) @property)
(qualified_type module: (identifier) @namespace)
(primitive_type (identifier) @type.builtin)
(generic_type) @type
(shape_type element: (identifier) @type.builtin)

; -- the measure a value is counted in --------------------------------

(measure) @attribute
(attribute name: (identifier) @attribute)
(expect_attribute) @attribute

; -- what is written down ---------------------------------------------

(string) @string
(integer) @number
(float) @number.float
(character) @character
(boolean) @boolean
(empty) @constant.builtin
(self_expression) @variable.builtin
(self_parameter) @variable.builtin

(line_comment) @comment
(block_comment) @comment

; -- what is done ------------------------------------------------------

[
  "fn" "let" "mut" "struct" "impl" "enum" "type" "unit" "module"
  "comptime"
] @keyword

[ "if" "elif" "else" "match" "catch" ] @keyword.conditional
[ "while" "foreach" "break" "continue" ] @keyword.repeat
"return" @keyword.return
[ "and" "or" "not" ] @keyword.operator
"λ" @keyword.function

(unary_expression operator: _ @operator)
(binary_expression operator: _ @operator)
(quantifier_expression operator: _ @operator)
(combinator_expression operator: _ @operator)
(operator_section) @operator

[
  "←" "<-" "→" "->" ":=" "…" "?" "!" "#" "¤" "@" "$"
] @operator

[ "(" ")" "[" "]" "{" "}" "⸨" "⸩" "⟦" "⟧" "⟪" "⟫" ] @punctuation.bracket
[ "," ":" ";" "." "|" ] @punctuation.delimiter
