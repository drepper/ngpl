/**
 * @file NGPL grammar for tree-sitter
 * @license MIT
 *
 * NGPL lays its blocks out by indentation, so the newline that ends a
 * statement and the indent that opens a block are handed over by the
 * external scanner in src/scanner.c.  Two things suppress them, and
 * both fall out of what the parser can accept at the point it has
 * reached: a line inside brackets, and a line whose last token is an
 * operator still waiting for its right-hand side.
 *
 * The binding powers are the compiler's own, from bin_bp() in
 * src/parse.ngpl, doubled so that the quantifiers can sit between the
 * comparisons and the range as they do there.
 */

/// <reference types="tree-sitter-cli/dsl" />
// @ts-check

const PREC = {
  or: 4,          // or ??
  and: 6,         // and
  lor: 8,         // ∨
  lxor: 10,       // ⊕ ⊼ ⊽
  land: 12,       // ∧
  compare: 14,    // = ≠ < > <= >= ⊑ ⊒
  quantifier: 15, // ∀ ∃ ∄ -- a comparison ends one, a range is inside it
  range: 16,      // …
  minmax: 18,     // ⌈ ⌊ ∊ ⍳
  shift: 20,      // « »
  bor: 22,        // |
  bxor: 24,       // ^
  band: 26,       // &
  add: 28,        // + - ⊞ ⊟
  concat: 30,     // ⧺
  mul: 32,        // × ÷ % ⊠
  reshape: 34,    // ⍴
  unary: 40,      // ⁻ not ¬ ~ # &
  postfix: 50,    // a.b  a(x)  a[i]
};

module.exports = grammar({
  name: 'ngpl',

  externals: $ => [
    $._newline,
    $._indent,
    $._dedent,
    $.string,
    $._error_sentinel,
  ],

  // A line break the scanner declines to make a token of -- inside
  // brackets, or after an operator still waiting for its right-hand
  // side -- is whitespace like any other.
  extras: $ => [/[ \t\r\n]/, $.line_comment, $.block_comment],

  word: $ => $.identifier,

  // `while x :` reads as a test or as a binding until what follows the
  // colon says which
  conflicts: $ => [
    [$._expression, $.binding],
    [$._expression, $.annotated_expression],
    // in an attribute, a name followed by a bracket is a subscript or
    // a shape until what stands inside the bracket says which
    [$._expression, $.shape_type],
    // a lambda whose body is a block closes the binding it stands in,
    // and may also stand where any other value does
    [$._expression, $.let_statement],
    // λx : i64: … -- the first colon gives the parameter its type and
    // the second opens the body; λx : … gives the body straight away
    [$.lambda_parameter],
    // in braces, `if c: e` reads as a value or as a statement
    [$._statement_in_braces, $.if_expression],
  ],

  supertypes: $ => [$._expression, $._statement, $._type, $._definition],

  rules: {
    source_file: $ => repeat(choice($._definition, $._newline)),

    // a statement is closed by the end of its line, and may be closed
    // with a semicolon before that
    _terminator: $ => seq(optional(';'), $._newline),

    // ------------------------------------------------------------------
    // What a file is made of
    // ------------------------------------------------------------------

    _definition: $ => choice(
      $.function_definition,
      $.struct_definition,
      $.impl_block,
      $.enum_definition,
      $.global_definition,
      $.type_alias,
      $.unit_definition,
      $.module_definition,
    ),

    // @expect error 2758 "…" -- a severity, perhaps a number, and the
    // message the compiler is to give
    expect_attribute: $ => seq(
      '@', 'expect',
      repeat(choice($.identifier, $.integer, $.string)),
    ),

    expect_statement: $ => seq($.expect_attribute, $._terminator),

    attribute: $ => seq(
      '@',
      field('name', $.identifier),
      // the parenthesis belongs to the attribute only where it follows
      // the name at once, as it is written
      optional(seq(token.immediate('('), optional(commaSep1($._attribute_argument)), ')')),
    ),

    _attribute_argument: $ => choice(
      seq(field('name', $.identifier), ':', $._expression),
      $._expression,
    ),

    // @sizeof(i32[]), @typeof(x) = u8[2,] -- brackets that hold nothing,
    // or hold a comma, are a shape rather than a subscript, which is
    // the one place a type reads differently from a value
    shape_type: $ => seq(
      field('element', $.identifier),
      '[',
      optional(seq(optional($._expression), repeat1(seq(',', optional($._expression))))),
      ']',
    ),

    function_definition: $ => seq(
      repeat(seq(choice($.attribute, $.expect_attribute), optional($._newline))),
      optional('comptime'),
      'fn',
      field('name', $.identifier),
      field('parameters', $.parameter_list),
      optional(seq($._arrow, field('return_type', $._type))),
      choice(
        seq(':', field('body', $.block)),
        seq(field('body', $.brace_block), $._terminator),
      ),
    ),

    parameter_list: $ => seq('(', optional(commaSep1(choice($.self_parameter, $.parameter))), ')'),

    self_parameter: $ => seq(optional(seq('&', optional('mut'))), 'self'),

    lambda_parameter: $ => seq(
      field('name', choice($.identifier, $.tuple_pattern)),
      optional(seq(':', optional('mut'), field('type', $._type))),
    ),

    parameter: $ => seq(
      field('name', choice($.identifier, $.tuple_pattern)),
      // args… : T -- the rest of the arguments, however many there are
      optional('…'),
      ':',
      optional('mut'),
      field('type', $._type),
    ),

    struct_definition: $ => seq(
      repeat(seq(choice($.attribute, $.expect_attribute), optional($._newline))),
      'struct',
      field('name', $.identifier),
      ':',
      $._newline,
      optional(seq(
        $._indent,
        repeat1(choice($.field_declaration, $.attribute_line, $._newline)),
        $._dedent,
      )),
    ),

    field_declaration: $ => seq(
      field('name', $.identifier),
      ':',
      field('type', $._type),
      $._terminator,
    ),

    attribute_line: $ => seq($.attribute, $._newline),

    impl_block: $ => seq(
      'impl',
      field('type', $.identifier),
      ':',
      $._newline,
      $._indent,
      repeat1(choice($.function_definition, $._newline)),
      $._dedent,
    ),

    enum_definition: $ => seq(
      repeat(seq(choice($.attribute, $.expect_attribute), optional($._newline))),
      'enum',
      field('name', $.identifier),
      optional(seq(':', field('type', $._type))),
      ':',
      $._newline,
      $._indent,
      repeat1(choice($.enumerator, $._newline)),
      $._dedent,
    ),

    enumerator: $ => seq(
      field('name', $.identifier),
      optional(seq('=', field('value', $._expression))),
      $._terminator,
    ),

    global_definition: $ => seq(
      repeat(seq(choice($.attribute, $.expect_attribute), optional($._newline))),
      'let',
      optional('mut'),
      field('name', $.identifier),
      optional(seq(':', optional('mut'), optional(field('type', $._type)))),
      choice('=', ':='),
      field('value', $._expression),
      $._terminator,
    ),

    type_alias: $ => seq(
      'type', field('name', $.identifier), '=', field('type', $.union_type), $._terminator,
    ),

    // a name may stand for one of several types
    union_type: $ => seq($._type, repeat(seq('|', $._type))),

    unit_definition: $ => seq(
      'unit',
      field('name', $.identifier),
      optional(choice(
        seq($._arrow, field('stands_for', $.identifier)),
        seq('=', field('derived_from', $._expression)),
      )),
      $._terminator,
    ),

    module_definition: $ => seq('module', choice(
      seq(optional('.'), field('name', $.identifier), repeat(seq('.', $.identifier))),
      '.',
    ), $._terminator),

    // ------------------------------------------------------------------
    // Types
    // ------------------------------------------------------------------

    _type: $ => choice(
      $.primitive_type,
      $.empty,
      $.measure,
      $.borrowed_type,
      $.array_type,
      $.optional_type,
      $.expected_type,
      $.tuple_type,
      $.measured_type,
      $.generic_type,
      $.qualified_type,
    ),

    primitive_type: $ => $.identifier,

    generic_type: $ => token(seq(/[A-Za-z_][A-Za-z0-9_]*/, repeat1("'"))),

    qualified_type: $ => seq(
      field('module', $.identifier), '.', field('name', $.identifier),
      optional(seq('(', commaSep1($._type), ')')),
    ),

    borrowed_type: $ => prec(2, seq('&', optional('mut'), $._type)),

    measured_type: $ => prec(3, seq($._type, $.measure)),

    measure: $ => seq('¤', choice($.identifier, $.string)),

    array_type: $ => prec(4, seq(
      $._type, '[', optional($._expression),
      repeat(seq(',', optional($._expression))), ']',
    )),

    optional_type: $ => prec(4, seq($._type, '?', optional(choice($.identifier, $.qualified_type)))),

    // T! is the type a call is expected to answer with
    expected_type: $ => prec(4, seq($._type, '!')),

    tuple_type: $ => seq('(', $._type, repeat(seq(',', $._type)), ')'),

    // ------------------------------------------------------------------
    // Statements
    // ------------------------------------------------------------------

    block: $ => choice($.indented_block, seq($.brace_block, $._newline), $._statement),

    indented_block: $ => seq(
      $._newline, $._indent, repeat1(choice($._statement, $._newline)), $._dedent,
    ),

    _statement: $ => choice(
      $.let_statement,
      $.assignment,
      $.if_statement,
      $.match_statement,
      $.while_statement,
      $.foreach_statement,
      $.return_statement,
      $.break_statement,
      $.continue_statement,
      $.expression_statement,
      $.catch_statement,
      $.label,
      $.expect_statement,
      $.nested_function,
      $.type_alias,
    ),

    nested_function: $ => seq(
      'fn',
      field('name', $.identifier),
      field('parameters', $.parameter_list),
      optional(seq($._arrow, field('return_type', $._type))),
      choice(
        seq(':', field('body', $.block)),
        seq(field('body', $.brace_block), $._terminator),
      ),
    ),

    catch_statement: $ => seq('catch', ':', field('body', $.block)),

    // a name a loop may be left by
    label: $ => seq(field('name', $.identifier), ':', $._newline),

    let_statement: $ => seq(
      'let',
      optional('mut'),
      field('name', choice($.identifier, $.tuple_pattern)),
      optional($.measure),
      optional(seq(':', optional('mut'), optional(field('type', $._type)))),
      choice('=', ':='),
      choice(
        seq(field('value', $._expression), $._terminator),
        field('value', $.if_statement),
        field('value', $.match_statement),
        field('value', $.block_lambda),
      ),
    ),

    tuple_pattern: $ => seq('(', commaSep1(choice($.identifier, $.tuple_pattern)), ')'),

    assignment: $ => seq(
      field('left', $._expression),
      $._assign,
      field('right', $._expression),
      $._terminator,
    ),

    expression_statement: $ => seq($._expression, $._terminator),

    return_statement: $ => seq('return', optional($._expression), $._terminator),
    break_statement: $ => seq('break', optional(field('label', $.identifier)), $._terminator),
    continue_statement: $ => seq('continue', optional(field('label', $.identifier)), $._terminator),

    if_statement: $ => prec.right(seq(
      'if', field('condition', $._expression), field('consequence', $._body),
      repeat($.elif_clause),
      optional($.else_clause),
    )),

    elif_clause: $ => seq('elif', field('condition', $._expression), field('consequence', $._body)),
    else_clause: $ => seq('else', field('alternative', $._body)),

    // a block written in braces needs no colon before it; one laid out
    // by indentation is introduced by one
    _body: $ => prec.right(choice(seq(':', $.block), seq($.brace_block, optional($._newline)))),

    while_statement: $ => seq(
      'while',
      field('condition', choice($._expression, $.binding)),
      field('body', $._body),
    ),

    // `while e := it.next():` -- the test binds what it answers, and
    // the block runs for as long as there is something to bind
    binding: $ => seq(
      field('name', $.identifier),
      optional(seq(':', optional('mut'), optional(field('type', $._type)))),
      choice(':=', '='),
      field('value', $._expression),
    ),

    foreach_statement: $ => seq(
      'foreach',
      field('pattern', commaSep1(choice($.identifier, $.tuple_pattern))),
      optional(seq(':', optional('mut'), optional(field('type', $._type)))),
      choice(':=', '='),
      field('iterable', commaSep1($._expression)),
      field('body', $._body),
    ),

    match_statement: $ => seq(
      'match', field('value', $._expression), ':', $._newline,
      $._indent, repeat1(choice($.match_arm, $._newline)), $._dedent,
    ),

    match_arm: $ => seq(
      field('pattern', $._expression),
      ':',
      field('body', $.block),
    ),

    // ------------------------------------------------------------------
    // Expressions
    // ------------------------------------------------------------------

    _expression: $ => choice(
      $.identifier,
      $.integer,
      $.float,
      $.string,
      $.character,
      $.boolean,
      $.empty,
      $.self_expression,
      $.measured_literal,
      $.unary_expression,
      $.binary_expression,
      $.quantifier_expression,
      $.combinator_expression,
      $.range_expression,
      $.call_expression,
      $.field_expression,
      $.index_expression,
      $.slice_expression,
      $.parenthesized_expression,
      $.tuple_expression,
      $.array_literal,
      $.dict_literal,
      $.struct_literal,
      $.lambda,
      $.block_lambda,
      $.if_expression,
      $.some_expression,
      $.none_expression,
      $.attribute,
      $.annotated_expression,
      $.measure,
      $.operator_name,
      $.macro_call,
      $.quotation,
      $.splice,
      $.shape_type,
      $.optional_expression,
    ),

    optional_expression: $ => prec(PREC.postfix, seq($._expression, '?')),

    // @listable λx : i64 → i64: … -- what the attribute is about follows it
    annotated_expression: $ => prec.right(seq($.attribute, $._expression)),

    self_expression: $ => 'self',

    measured_literal: $ => prec(PREC.postfix + 1, seq(choice($.integer, $.identifier), $.measure)),

    parenthesized_expression: $ => seq('(', $._expression, ')'),

    tuple_expression: $ => seq('(', $._expression, repeat1(seq(',', $._expression)), ')'),

    array_literal: $ => seq('[', optional(commaSep1($._expression)), optional(','), ']'),

    dict_literal: $ => seq(
      '⸨',
      optional(commaSep1(choice(
        seq(field('key', $._expression), ':', field('value', $._expression)),
        $._expression,
      ))),
      optional(','),
      '⸩',
    ),

    struct_literal: $ => prec(1, seq(
      field('name', $.identifier),
      '{',
      commaSep1(seq(field('field', $.identifier), ':', $._expression)),
      optional(','),
      '}',
    )),

    // statements between braces, closed by a semicolon or by the end of
    // the line they are written on
    brace_block: $ => seq(
      '{',
      repeat(choice($._statement_in_braces, ';', $._newline)),
      '}',
    ),

    _statement_in_braces: $ => choice(
      $._expression,
      $.let_in_braces,
      $.assignment_in_braces,
      $.brace_if,
      $.brace_while,
      $.brace_foreach,
      $.brace_return,
      'break',
      'continue',
    ),

    brace_if: $ => prec.right(seq(
      'if', field('condition', $._expression), $._brace_intro,
      repeat(seq('elif', $._expression, $._brace_intro)),
      optional(seq('else', $._brace_intro)),
    )),

    _brace_intro: $ => choice(seq(':', $._brace_body), $.brace_block),

    brace_while: $ => seq('while', field('condition', choice($._expression, $.binding)),
                          $._brace_intro),

    brace_foreach: $ => seq(
      'foreach',
      field('pattern', commaSep1(choice($.identifier, $.tuple_pattern))),
      ':=',
      field('iterable', commaSep1($._expression)),
      $._brace_intro,
    ),

    brace_return: $ => prec.right(seq('return', optional($._expression))),

    _brace_body: $ => choice($.brace_block, $._statement_in_braces),

    let_in_braces: $ => seq('let', optional('mut'), $.identifier,
                            optional(seq(':', optional('mut'), optional($._type))),
                            choice('=', ':='), $._expression),

    assignment_in_braces: $ => seq($._expression, $._assign, $._expression),

    some_expression: $ => seq('⊨', '(', $._expression, ')'),

    none_expression: $ => seq('⊭', '(', optional($._expression), ')'),

    if_expression: $ => prec.right(seq(
      'if', field('condition', $._expression), ':', field('consequence', $._expression),
      repeat(seq('elif', $._expression, ':', $._expression)),
      'else', ':', field('alternative', $._expression),
    )),

    lambda: $ => seq(
      'λ',
      optional(commaSep1($.lambda_parameter)),
      optional($.capture_list),
      optional(seq($._arrow, field('return_type', $._type))),
      ':',
      field('body', $._expression),
    ),

    block_lambda: $ => seq(
      'λ',
      optional(commaSep1($.lambda_parameter)),
      optional($.capture_list),
      optional(seq($._arrow, field('return_type', $._type))),
      ':',
      field('body', choice($.indented_block, $.brace_block)),
    ),

    capture_list: $ => seq('|', optional(commaSep1($.identifier)), '|'),

    call_expression: $ => prec(PREC.postfix, seq(
      field('function', $._expression),
      field('arguments', $.argument_list),
    )),

    field_expression: $ => prec(PREC.postfix, seq(
      field('receiver', $._expression), '.', field('field', $.identifier),
    )),

    argument_list: $ => seq('(', optional(commaSep1($._expression)), ')'),

    index_expression: $ => prec(PREC.postfix, seq(
      field('container', $._expression), '[', optional(commaSep1($._expression)), ']',
    )),

    slice_expression: $ => prec(PREC.postfix, seq(
      field('container', $._expression), '[', $.range_expression, ']',
    )),

    range_expression: $ => prec.left(PREC.range, seq(
      field('start', $._expression),
      repeat1(seq('…', $._expression)),
    )),

    unary_expression: $ => prec(PREC.unary, seq(
      field('operator', choice('⁻', 'not', '¬', '~', '#', '&', seq('&', 'mut'),
                               '√', '∛', '∜', '⊃', '⊇', '⊆', '⊂', '⌈', '⌊')),
      field('operand', $._expression),
    )),

    quantifier_expression: $ => prec.left(PREC.quantifier, seq(
      field('left', $._expression),
      field('operator', choice('∀', '∃', '∄')),
      field('right', $._expression),
    )),

    // an operator written where a function is wanted: +⌿ v folds with
    // addition, as ⧺⌿ v joins with concatenation
    // ※× names the operator rather than working with it
    operator_name: $ => seq('※', $.operator_section),

    // ⟪ … ⟫ is a piece of program written down, and $(…) puts one in
    quotation: $ => seq('⟪', repeat(choice($._expression, ',', ':', $._newline)), '⟫'),

    splice: $ => seq('$', choice(seq('(', $._expression, ')'), $.identifier)),

    macro_call: $ => prec(PREC.postfix, seq(
      field('macro', $._expression), '⟦', optional(commaSep1($._expression)), '⟧',
    )),

    operator_section: $ => choice(
      '+', '-', '×', '÷', '%', '⧺', '⌈', '⌊', '⊞', '⊟', '⊠',
      '∧', '∨', '⊕', '⊼', '⊽', '|', '&', '^', '«', '»',
    ),

    // f ⌿ v folds, f ⍀ v folds from the right, f ¨ v asks f of each
    combinator_expression: $ => prec.left(PREC.quantifier, seq(
      field('function', choice($._expression, $.operator_section)),
      field('operator', choice('⌿', '⍀', '¨')),
      field('container', $._expression),
    )),

    binary_expression: $ => {
      const table = [
        [PREC.or, choice('or', '??')],
        [PREC.and, 'and'],
        [PREC.lor, '∨'],
        [PREC.lxor, choice('⊕', '⊼', '⊽')],
        [PREC.land, '∧'],
        [PREC.compare, choice('=', '==', '≠', '!=', '<', '>', '<=', '>=', '⊑', '⊒',
                             '≅', '≇', '⪅', '⪆', '⪉', '⪊',
                             '⊂', '⊃', '⊆', '⊇', '∖', '∪', '∩')],
        [PREC.minmax, choice('⌈', '⌊', '∊', '⍳')],
        [PREC.shift, choice('«', '»', '<<', '>>', '↺', '↻')],
        [PREC.bor, '|'],
        [PREC.bxor, '^'],
        [PREC.band, '&'],
        [PREC.add, choice('+', '-', '⊞', '⊟')],
        [PREC.concat, '⧺'],
        [PREC.mul, choice('×', '÷', '%', '⊠')],
        [PREC.reshape, '⍴'],
        [PREC.reshape + 2, '↑'],
      ];
      return choice(...table.map(([precedence, operator]) =>
        prec.left(precedence, seq(
          field('left', $._expression),
          field('operator', operator),
          field('right', $._expression),
        ))));
    },

    // ------------------------------------------------------------------
    // Tokens
    // ------------------------------------------------------------------

    identifier: $ =>
      /[A-Za-z_\u00C0-\u024F\u0391-\u03BA\u03BC-\u03FF][A-Za-z0-9_\u00C0-\u024F\u0391-\u03BA\u03BC-\u03FF\u2080-\u2089]*/,

    // the language writes each of these two both ways
    _arrow: $ => choice('→', '->'),
    _assign: $ => choice('←', '<-'),

    integer: $ => token(seq(
      choice(/[0-9][0-9_]*/, /0[xX][0-9A-Fa-f_]+/, /0[bB][01_]+/, /0[oO][0-7_]+/),
      optional(/[iu][0-9]+(fast)?|usize|isize|ptrdiff|byte|int|f16|f32|f64|bfloat16|float/),
    )),

    float: $ => token(seq(
      choice(
        seq(/[0-9][0-9_]*/, '.', /[0-9][0-9_]*/, optional(/[eE][-+]?[0-9]+/)),
        seq(/[0-9][0-9_]*/, /[eE][-+]?[0-9]+/),
        seq(/0[xX][0-9A-Fa-f_]*/, optional(seq('.', /[0-9A-Fa-f_]+/)), /[pP][-+]?[0-9]+/),
      ),
      optional(/f16|f32|f64|bfloat16|float/),
    )),

    character: $ => token(seq("'", choice(/[^'\\]/, seq('\\', /./), seq('\\u{', /[0-9A-Fa-f]+/, '}')), "'")),

    boolean: $ => choice('true', 'false'),

    empty: $ => '∅',

    line_comment: $ => token(seq('//', /[^\n]*/)),

    block_comment: $ => token(seq('/*', /[^*]*\*+([^/*][^*]*\*+)*/, '/')),
  },
});

function commaSep1(rule) {
  return seq(rule, repeat(seq(',', rule)));
}

function sepBy(sep, rule) {
  return optional(seq(rule, repeat(seq(sep, rule))));
}
