"""Abstract Syntax Tree nodes for the NGPL language.

Each class represents one construct in the source language. The parser builds
a tree of these nodes; the evaluator walks the tree to produce results.

Every node may carry an optional `pos` attribute set by the parser,
a tuple of (line, col, end_col) pointing back to the source token(s).
"""


def set_pos(node, line: int, col: int, end_col: int | None = None):
    """Attach source position to an AST node and return it."""
    node.pos = (line, col, end_col)
    return node


class IntLit:
    """Integer literal with an optional bit-width suffix."""

    def __init__(self, value: int, width: str = "int"):
        self.value = value
        self.width = width
        # The boxed value, made when the literal is first read and kept
        # after.  A literal is the same value however often it is read
        # and a boxed integer is never changed in place, so one box
        # serves every reading; in a loop this is the difference
        # between one allocation and one for every turn.
        self.boxed = None


class FloatLit:
    """Floating-point literal with an optional width suffix."""

    def __init__(self, value: float, width: str = "float"):
        self.value = value
        self.width = width


class CharLit:
    """Character literal: one Unicode scalar value, written 'a'."""

    def __init__(self, code: int):
        self.code = code


class StrLit:
    """String literal with escape processing."""

    def __init__(self, text: str):
        self.text = text


class BoolLit:
    """Boolean literal: true or false."""

    def __init__(self, value: bool):
        self.value = value


class NoneLit:
    """The none literal (empty optional)."""

    pass


class VarRef:
    """Reference to a variable by name."""

    def __init__(self, name: str):
        self.name = name


class RefExpr:
    """Reference expression: &name at a call site."""

    def __init__(self, name: str):
        self.name = name


class BorrowExpr:
    """Borrow of a container: &expr or &mut expr in a foreach iterable.

    A shared borrow (is_mut false) lets the loop read the elements; a
    mutable borrow lets it write to them through the loop variable.
    """

    def __init__(self, expr, is_mut: bool):
        self.expr = expr
        self.is_mut = is_mut


class BinOp:
    """Binary operator: + - × ÷ = ≠ < > <= >= and or."""

    def __init__(self, op: str, left, right):
        self.op = op  # one of "+", "-", "×", "÷", "=", "≠", "<", ">", "<=", ">=", "and", "or"
        self.left = left
        self.right = right


class UnaryOp:
    """Unary operator: ⁻ (negation), not, opt.is_none."""

    def __init__(self, op: str, operand):
        self.op = op  # "⁻", "not", "is_none"
        self.operand = operand


class IfStmt:
    """Conditional statement.

    cons: the true branch (list of statements)
    alt:  the false/elif branches, each a tuple (condition_stmts, body_stmts)
          or None for a plain else without a new condition
    """

    # Set where the if was written as an expression rather than a
    # statement.  Both are the same node -- what differs is that a
    # value was wanted, so every branch has to supply one.
    is_value = False

    def __init__(self, cond, cons, alt=None, hint: str | None = None):
        self.cond = cond       # expression
        self.cons = cons       # list of statements
        self.alt = alt         # tuple (cond, cons, rest) or None
        # "likely" or "unlikely" from an annotation, saying which way
        # the condition is expected to go.  A hint never changes what
        # the program computes.
        self.hint = hint


def if_branch_bodies(node):
    """Every branch of an if chain, as a list of statements.

    The chain is nested tuples, each (condition, body) or (condition,
    body, rest); an else is the one whose condition is None.  A branch
    that is not there -- an if with no else -- is not a branch, and
    nothing is yielded for it.
    """
    yield node.cons
    alt = node.alt
    while alt is not None:
        yield alt[1]
        alt = alt[2] if len(alt) == 3 else None


def if_has_else(node) -> bool:
    """Whether an if chain ends in an else rather than running out.

    One that runs out can fall past every branch, so what it hands back
    where it does is nothing, and its value is optional rather than
    whatever its branches say.
    """
    alt = node.alt
    while alt is not None:
        if alt[0] is None:
            return True
        alt = alt[2] if len(alt) == 3 else None
    return False


def if_branch_values(node):
    """The expression each branch of an if hands back.

    A branch that ends in something else -- a return, a loop -- hands
    nothing back, and nothing is yielded for it.  What is yielded is
    the value of the if where that branch runs, which is what lets a
    walk that knows about expressions see through one.
    """
    for body in if_branch_bodies(node):
        if body and isinstance(body[-1], ExprStmt):
            yield body[-1].expr


class WhileStmt:
    """While loop.

    var_name, when set, names a variable bound to the condition's value
    at the start of every iteration, as `while e := next()` does.  The
    bound value is then what decides whether the body runs.

    label, when set, is the name written on the line above the loop,
    which a break or a continue inside it may take; label_pos is where
    that name was written.
    """

    def __init__(self, cond, body, var_name: str | None = None,
                 var_type: str | None = None, var_is_mut: bool = False,
                 label: str | None = None):
        self.label = label
        self.label_pos = None
        self.cond = cond
        self.body = body
        self.var_name = var_name
        self.var_type = var_type
        self.var_is_mut = var_is_mut


class ReturnStmt:
    """Return statement with an optional expression."""

    def __init__(self, value=None):
        self.value = value  # expression or None


class FuncDef:
    """Function definition at top level.

    name:      function identifier
    params:    list of (name, type_annotation_or_None) tuples
    ret_type:  declared return type string.  A signature that
               writes none records ∅, which is what it means.
    body:      list of statements
    is_start:  True if annotated with @start
    """

    def __init__(self, name, params, ret_type, body, is_start=False,
                 is_test=False, test_refs=None,
                 expect_annotations: list[tuple[str, str]] | None = None,
                 is_replaceable: bool = False,
                 pack_param: tuple[str, str | None] | None = None,
                 param_units: dict[str, object] | None = None,
                 is_impure: bool = False,
                 param_refs: set[str] | None = None,
                 param_muts: set[str] | None = None,
                 hint: str | None = None,
                 ret_unit=None,
                 is_listable: bool = False,
                 is_noreturn: bool = False,
                 preconditions: list | None = None,
                 postconditions: list | None = None,
                 is_comptime: bool = False):
        self.name = name
        self.is_build = False
        # @ignorable: a caller may drop what this hands back
        self.is_ignorable = False
        self.params = params
        # Where each parameter was written, for diagnostics about it.
        self.param_positions: dict[str, tuple[int, int, int | None]] = {}
        # Where the return type was written, or None where the
        # signature left it off and ∅ was recorded for it.
        self.ret_type_pos: tuple[int, int, int | None] | None = None
        self.param_refs: set[str] = param_refs or set()
        self.param_muts: set[str] = param_muts or set()
        self.ret_type = ret_type
        self.body = body
        self.is_start = is_start
        self.is_test = is_test
        self.test_refs: list[str] = test_refs or []
        self.expect_annotations: list[tuple[str, str]] = expect_annotations or []
        self.is_replaceable = is_replaceable
        self.pack_param = pack_param
        self.param_units: dict[str, object] = param_units or {}
        self.is_impure = is_impure
        # Unlike a hint, this changes what the function computes for an
        # argument it did not ask for, so it has to reach the runtime.
        self.is_listable = is_listable
        # Whether the function hands control back at all.
        self.is_noreturn = is_noreturn
        # What the function holds to on the way in and on the way out.
        self.preconditions = preconditions or []
        self.postconditions = postconditions or []
        # "hot" or "cold" from an annotation, saying how often the
        # function is expected to run.  A hint never changes what the
        # function computes.
        self.hint = hint
        # The unit the return type states, or None where it states none.
        self.ret_unit = ret_unit
        # Whether the function is there before the program runs, which
        # is what lets a macro call it.
        self.is_comptime = is_comptime


class VarDef:
    """Variable definition with initializer."""

    def __init__(self, name, type_annotation, init_expr, is_const: bool = False,
                 unit_spec=None):
        self.name = name
        self.type_annotation = type_annotation  # type string or None
        self.init_expr = init_expr
        self.is_const = is_const
        self.unit_spec = unit_spec


class DestructureDef:
    """Definition taking a tuple apart: let (a, b) := expr.

    names holds one name per element, in the order the tuple has them,
    with the discard target where an element is not wanted.  The type
    annotation, where there is one, is the tuple's, so each name takes
    the type of its own position.
    """

    def __init__(self, names, type_annotation, init_expr,
                 is_const: bool = True):
        self.names = names
        self.type_annotation = type_annotation
        self.init_expr = init_expr
        self.is_const = is_const


class ExprStmt:
    """An expression used as a statement (discard result)."""

    def __init__(self, expr, had_semi=False):
        self.expr = expr
        # Whether a ';' followed: the full language's semicolon
        # discards the value, which matters when this is the last
        # statement of a body.
        self.had_semi = had_semi


class FuncCall:
    """Function call: name(arg1, arg2, ...)."""

    def __init__(self, name, args=None):
        self.name = name
        self.args = args or []  # list of expression nodes


class MethodCall:
    """Method call: object.method(args)."""

    def __init__(self, obj, method, args=None):
        self.obj = obj
        self.method = method
        self.args = args or []


class OptSome:
    """Constructor for an optional value: some(expr)."""

    def __init__(self, value):
        self.value = value


class GetAttr:
    """Attribute access: object.attr."""

    def __init__(self, obj, attr):
        self.obj = obj
        self.attr = attr


class ArrayLit:
    """Array literal: [expr, expr, ...]."""

    def __init__(self, elements):
        self.elements = elements  # list of expression AST nodes


class BreakStmt:
    """`break` or `break label` — leave a loop."""

    __slots__ = ("label", "pos")

    def __init__(self, label=None):
        self.label = label
        self.pos = None


class ContinueStmt:
    """`continue` or `continue label` — go round again."""

    __slots__ = ("label", "pos")

    def __init__(self, label=None):
        self.label = label
        self.pos = None


class MacroRulesDef:
    """`@macro_rules` -- a macro written as a list of rewrite rules.

    Each rule is a MacroRule.  They are tried in order and the first
    one whose pattern matches decides the expansion, which is why a
    catch-all rule is written last.
    """

    def __init__(self, name: str, rules: list):
        self.name = name
        self.rules = rules
        self.pos = None


class MacroRule:
    """One rewrite: what the arguments have to look like, and what for.

    `patterns` is one pattern per macro argument, and `template` is
    what replaces the invocation -- an expression, or a list of
    statements where the rule writes a block.  Both are ordinary
    expression trees, with MetaVar standing where a hole is written.
    """

    def __init__(self, patterns: list, template, pos=None):
        self.patterns = patterns
        self.template = template
        self.pos = pos


class MetaVar:
    """`$a` in a rule -- what a pattern captures and a template fills."""

    def __init__(self, name: str):
        self.name = name
        self.pos = None


class MacroFuncDef:
    """`macro` -- a macro written as a function over the program's text.

    `func` is an ordinary FuncDef whose parameters are handed the parse
    trees of what the invocation was written with, and whose answer is
    the tree that replaces the invocation.  It runs while the program
    is being installed, not while it runs.
    """

    def __init__(self, name: str, func):
        self.name = name
        self.func = func
        self.pos = None


class Quote:
    """`⟪ … ⟫` -- a piece of program held rather than run.

    Evaluating one answers the tree written inside it, with whatever
    `$` puts back into it already in place.
    """

    def __init__(self, tree, is_block: bool = False):
        self.tree = tree
        self.is_block = is_block
        self.pos = None


class Reflect:
    """`※name` -- what a name refers to, held as a piece of the program.

    Where a quote holds whatever text is written in it, this holds one
    entity: a function, an operator, a constant, a variable.  C++26
    says the same thing with ^^; the glyph here is the one Unicode
    calls a reference mark, which is what this is.
    """

    def __init__(self, tree):
        self.tree = tree
        self.pos = None


class Splice:
    """`$e` inside a quote -- put what e answers into the tree here."""

    def __init__(self, expr):
        self.expr = expr
        self.pos = None


class MacroCall:
    """`name⟦args⟧` -- an invocation replaced by what the macro answers.

    Nothing evaluates one of these: expansion replaces it before
    anything runs, and reaching the evaluator means expansion did not.
    """

    def __init__(self, name: str, args: list):
        self.name = name
        self.args = args
        self.pos = None


class Condition:
    """A `@pre` or `@post` a function holds to.

    `name` is what a postcondition calls the value that comes back, or
    None where it says nothing about it.  `pos` is where the keyword
    was written, so a violation is reported at the condition rather
    than at whatever the function was doing when it broke.
    """

    __slots__ = ("which", "name", "expr", "pos")

    def __init__(self, which, name, expr, pos):
        self.which = which
        self.name = name
        self.expr = expr
        self.pos = pos


class HashLit:
    """Dictionary literal: ⸨key: value, …⸩."""

    def __init__(self, pairs):
        self.pairs = pairs  # list of (key expr, value expr)


class SetLit:
    """Set literal: ⸨value, …⸩."""

    def __init__(self, elements):
        self.elements = elements


class EmptyCollectionLit:
    """⸨⸩ — which of the two it is, only a type can say."""

    def __init__(self):
        pass


class Subscript:
    """Subscript access: obj[i] or multi-dimensional obj[i, j, ...]."""

    def __init__(self, obj, indices: list):
        self.obj = obj
        self.indices = indices


class SliceAccess:
    """Slice access: obj[start…end] (inclusive on both ends)."""

    def __init__(self, obj, start, end):
        self.obj = obj
        self.start = start
        self.end = end


class MultiSlice:
    """Multi-dimensional slice: obj[spec, spec, ...].

    Each spec is either ("index", expr) for point access or
    ("range", start, end) for a slice along that dimension.
    """

    def __init__(self, obj, specs: list):
        self.obj = obj
        self.specs = specs


class LimitExpr:
    """@min(T) or @max(T): the extreme value a numeric type can hold.

    kind is "min" or "max".  The operand names a type, or names
    something whose type is asked about instead.
    """

    def __init__(self, kind: str, expr):
        self.kind = kind
        self.expr = expr


class OldExpr:
    """@old(expr) -- what expr was when the call began.

    A postcondition is read where the answer is, by which time a
    parameter may have been changed by the body.  `@old` is how it says
    what the parameter was rather than what it has become: the
    expression is read once, before a statement of the body runs, and
    the postcondition sees that.

    Eiffel spells it `old`, Ada `\'Old`; the annotation form is this
    language\'s, and keeps the word available as a name.
    """

    def __init__(self, expr):
        self.expr = expr


class DropUnitExpr:
    """@dropunit(expr): the value without the unit it carries.

    A unit is part of a type, so parting with one is a real change and
    is written down rather than happening quietly at a boundary.
    """

    def __init__(self, expr):
        self.expr = expr


class TryUnwrap:
    """Postfix ? operator: unwrap optional or propagate none."""

    def __init__(self, expr):
        self.expr = expr


class ArrayAlloc:
    """Array allocation: new type[size] or var name : type[size] = init.

    A multi-dimensional allocation keeps its outermost extent in
    size_expr and the rest in rest_dims, so `i32[2,3]` is two rows of
    the three-element rows built one level down.
    """

    def __init__(self, element_type, size_expr, init_expr=None, rest_dims=None):
        self.element_type = element_type  # type string like "i32", "u64"
        self.size_expr = size_expr        # expression AST node for the count
        self.init_expr = init_expr        # optional per-element initializer
        self.rest_dims = rest_dims or []  # expressions for further dimensions


class RangeExpr:
    """Range expression: start…end or start…step…end (inclusive on both ends)."""

    def __init__(self, start, end, step=None):
        self.start = start
        self.end = end
        self.step = step


class ForEachStmt:
    """Foreach loop: foreach vars = iterables block.

    vars:      list of (name, type_or_None) tuples
    iterables: list of expressions (RangeExpr or container)
    body:      list of statements
    label:     the name written on the line above the loop, if any,
               with label_pos saying where it was written
    """

    def __init__(self, vars, iterables, body, is_comptime: bool = False,
                 label: str | None = None):
        self.label = label
        self.label_pos = None
        self.vars = vars
        self.iterables = iterables
        self.body = body
        self.is_comptime = is_comptime


class ExpectStmt:
    """Statement annotated with @expect error/warning "pattern".

    expectations: list of (level, regex_pattern) tuples
    stmt:         the wrapped statement AST node
    """

    def __init__(self, expectations: list[tuple[str, str]], stmt):
        self.expectations = expectations
        self.stmt = stmt


class WrapExpr:
    """Expression annotated with @wrap for wrapping arithmetic.

    All arithmetic operations within the wrapped expression use modular
    semantics regardless of signedness.
    """

    def __init__(self, expr):
        self.expr = expr


class LambdaExpr:
    """Anonymous function: λparam:type, ... |captures| -> ret_type: body.

    body is either a single expression node or a list of statement nodes.
    """

    # Set where `@listable` was written in front of the λ.  A lambda
    # is a function like any other and threads over a container the
    # same way; what it lacked was somewhere to say so.
    is_listable = False

    def __init__(self, params: list[tuple[str, str]], captures: list[str] | None,
                 ret_type: str, body, is_listable: bool = False,
                 param_units: dict[str, object] | None = None):
        self.params = params
        self.captures = captures
        self.ret_type = ret_type
        self.body = body
        self.is_listable = is_listable
        # A lambda's parameter states a measure the way a named
        # function's does, `λi ¤ptrdiff : i64 → …`, and for the same
        # reason: what is handed to it arrives measured, and a walk
        # over a measured range should not have to drop the measure to
        # be asked a question.
        self.param_units: dict[str, object] = param_units or {}


class MapExpr:
    """`f ¨ v` -- f applied to each of the things v holds.

    The answer is an array of what f said, one for each, in the order
    they were held.
    """

    def __init__(self, func, container):
        self.func = func
        self.container = container
        self.pos = None


class QuantExpr:
    """`f ∀ v`, `f ∃ v` and `f ∄ v` -- whether f holds of them all, of
    any, or of none.

    kind is "all" for ∀, "any" for ∃ and "none" for ∄.  The shape is a
    fold's: what asks the question on the left, what is asked about on
    the right.
    """

    def __init__(self, kind, func, container):
        self.kind = kind
        self.func = func
        self.container = container
        self.pos = None


class ReshapeExpr:
    """Reshape expression: shape ⍴ data."""

    def __init__(self, shape, data):
        self.shape = shape
        self.data = data


class TupleLit:
    """Tuple literal: (expr, expr, ...)."""

    def __init__(self, elements):
        self.elements = elements


class CatchStmt:
    """Catch statement for scoped error handling.

    Errors from direct operations inside the block are caught and
    converted to return values based on the enclosing function's
    return type (optional or expected).  Errors from called functions
    propagate normally (syntactic scope only).
    """

    def __init__(self, body):
        self.body = body


class TypeOfExpr:
    """Type-of expression: @typeof(expr).

    Returns a TypeValue representing the runtime type of the expression.
    """

    def __init__(self, expr):
        self.expr = expr


class ResultOfExpr:
    """Result-of expression: @resultof(func_name).

    Returns a TypeValue representing the return type of the named function.
    """

    def __init__(self, name: str):
        self.name = name


class SizeOfExpr:
    """Size-of expression: @sizeof(expr).

    Returns the number of elements in a container or tuple.
    """

    def __init__(self, expr):
        self.expr = expr


class UnitOfExpr:
    """Unit-of expression: @unitof(expr).

    Returns a UnitOfValue representing the unit attached to the expression,
    or a dimensionless unit if the value has no unit.
    """

    def __init__(self, expr):
        self.expr = expr


class UnitRefExpr:
    """Standalone unit reference: ¤meter, ¤second, etc.

    Produces a UnitOfValue for comparison with @unitof results.
    """

    def __init__(self, unit_spec):
        self.unit_spec = unit_spec


class StaticAssert:
    """Compile-time assertion: static_assert(cond) or static_assert(cond, msg).

    All arguments must be compile-time constant expressions.
    """

    def __init__(self, args: list):
        self.args = args


class StaticAssertEq:
    """Compile-time equality assertion: static_assert_eq(expected, actual).

    Both arguments must be compile-time constant expressions.
    """

    def __init__(self, expected, actual):
        self.expected = expected
        self.actual = actual


class EnumerateExpr:
    """Enumerate expression: enumerate(container).

    Wraps an iterable so that foreach yields (index, value) tuples.
    """

    def __init__(self, expr):
        self.expr = expr


class OperatorRef:
    """A binary operator written as a value: `⧺` in `⧺⌿ v`.

    An operator names an operation the way a function name does, so it
    may stand where a fold expects a function rather than having to be
    wrapped in a lambda that says the same thing at greater length.
    """

    def __init__(self, op: str):
        self.op = op


class FoldExpr:
    """Fold expression: func ⌿ container or func ⌿ (container, init).

    direction: "left" or "right"
    func: left operand, expression evaluating to a callable
    container: expression evaluating to an iterable
    init: optional initial accumulator value (None when omitted)
    """

    def __init__(self, direction: str, func, container, init=None):
        self.direction = direction
        self.func = func
        self.container = container
        self.init = init


class SumTypeDef:
    """Sum type definition: type NAME = A | B | C.

    A value of the type is a value of exactly one alternative, and
    carries which one.  The alternatives are named types, so the tag is
    the alternative's identity rather than a number the program has to
    keep in step with the data.
    """

    def __init__(self, name: str, alternatives: list[str]):
        self.name = name
        self.alternatives = alternatives


class TypeDef:
    """Type alias definition at top level: type NAME = TARGET [DESCRIPTION].

    `unit_spec` is what the alias measures, where the alias itself said
    so -- `type Duration = i64 ¤sec`.  Written there it belongs to the
    type rather than to every binding of it, which is the point of
    writing it there rather than at each one.
    """

    def __init__(self, name: str, target: str, description: str | None = None,
                 unit_spec=None):
        self.name = name
        self.target = target
        self.description = description
        self.unit_spec = unit_spec


class EnumDef:
    """Enum type definition at top level.

    name:            enum identifier
    underlying_type: optional storage type (e.g., "u8", "u32")
    members:         list of (name, explicit_value_or_None) tuples
    is_flag:         True if annotated with @flag (powers-of-two auto-values)
    """

    def __init__(self, name: str, underlying_type: str | None,
                 members: list[tuple[str, int | None]], is_flag: bool = False):
        self.name = name
        self.underlying_type = underlying_type
        self.members = members
        self.is_flag = is_flag


# ---------------------------------------------------------------------------
# Unit system AST nodes
# ---------------------------------------------------------------------------

class UnitExpr:
    """Expression with a unit annotation: expr ¤ unit_spec."""

    def __init__(self, expr, unit_spec):
        self.expr = expr
        self.unit_spec = unit_spec


class ModuleDef:
    """`module a` or `module .a.b`: what follows belongs to this module.

    Not a block.  The declaration says where the definitions after it
    live, until the next one says otherwise, so `full` is the whole
    path the parser worked out at the moment it was read.
    """

    def __init__(self, full: str, written: str):
        self.full = full
        # What the source said, for a message that quotes it back.
        self.written = written


class UnitDef:
    """Top-level unit definition: unit name [= formula] [→ decay]."""

    def __init__(self, name: str, formula, decay: str | None = None):
        self.name = name
        self.formula = formula
        # What this measure may stand in for, where one is asked for and
        # this is what there is.  None where it stands in for nothing.
        self.decay = decay


class UnitName:
    """Reference to a unit by name (builtin identifier or string)."""

    def __init__(self, name: str, is_string: bool = False):
        self.name = name
        self.is_string = is_string


class UnitBinOp:
    """Binary operation on units: * or /."""

    def __init__(self, op: str, left, right):
        self.op = op
        self.left = left
        self.right = right


class UnitSqrt:
    """Square root of a unit."""

    def __init__(self, operand):
        self.operand = operand


class UnitLit:
    """Numeric literal in a unit formula (conversion factor)."""

    def __init__(self, value: int):
        self.value = value


class StructDef:
    """Struct (product type) definition: struct Name: fields.

    repr_kind is the layout attribute from @repr(...), or None when the
    struct has no defined layout.
    """

    # What `@invariant(…)` said is always true of one of these, as a
    # list of expressions naming the fields.  A condition on the type
    # rather than on a function: every way of making or changing one
    # has to leave it holding.
    invariants: list = []

    def __init__(self, name: str, fields: list[tuple[str, str]],
                 repr_kind: str | None = None, field_units=None,
                 invariants=None):
        self.name = name
        self.fields = fields
        self.repr_kind = repr_kind
        self.invariants = list(invariants or [])
        # The unit each field's numbers count in, by field name; a
        # field not named here measures nothing.  Held as the parsed
        # spec, since the units a file defines register later.
        self.field_units = field_units or {}
        # Where each field's type was written, by field name.  A
        # complaint about a field is nearly always about its type, so
        # that is what a diagnostic points at.
        self.field_positions: dict[str, tuple[int, int, int | None]] = {}


class ImplBlock:
    """Implementation block: impl StructName: methods."""

    def __init__(self, struct_name: str, methods: list):
        self.struct_name = struct_name
        self.methods = methods


class StructLit:
    """Struct literal: Name { field: value, ... }."""

    def __init__(self, name: str, field_inits: list[tuple[str, object]]):
        self.name = name
        self.field_inits = field_inits


class ExpErr:
    """Constructor for a failed result: ⊭(expr)."""

    def __init__(self, value):
        self.value = value


class MatchArm:
    """One arm of a match: a pattern and the statements it guards.

    kind is "some" (⊨(name), binding the contained value), "err"
    (⊭(name)), "none" (∅), "type" (Type(name), one alternative of a sum
    type), "enum" (Enum.member, one value of an enumeration), or
    "wildcard" (_).  name is the bound name, set for every kind that
    binds; type_name is set for "type" and holds the enumeration's name
    for "enum", whose member name is in member.
    """

    def __init__(self, kind: str, name: str | None, body,
                 type_name: str | None = None, member: str | None = None):
        self.kind = kind
        self.name = name
        self.body = body
        self.type_name = type_name
        self.member = member


class MatchStmt:
    """match subject: arms — dispatch on the shape of a value."""

    def __init__(self, subject, arms: list[MatchArm]):
        self.subject = subject
        self.arms = arms


# Every node may be asked where it was written, and the evaluator asks
# tens of millions of times a run: once for each expression and each
# statement it reaches.  A class-level default answers the ones the
# parser never told, so the question is an attribute read rather than a
# lookup with a fallback.  Classes that keep `pos` in __slots__ set it
# in their own __init__ and are left alone.
for _cls in list(globals().values()):
    if isinstance(_cls, type) and _cls.__module__ == __name__ \
            and "__slots__" not in _cls.__dict__ \
            and "pos" not in _cls.__dict__:
        _cls.pos = None
del _cls
