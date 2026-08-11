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
    """Binary operator: + - × ÷ == != < > <= >= and or."""

    def __init__(self, op: str, left, right):
        self.op = op  # one of "+", "-", "×", "÷", "==", "!=", "<", ">", "<=", ">=", "and", "or"
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

    def __init__(self, cond, cons, alt=None, hint: str | None = None):
        self.cond = cond       # expression
        self.cons = cons       # list of statements
        self.alt = alt         # tuple (cond, cons, rest) or None
        # "likely" or "unlikely" from an annotation, saying which way
        # the condition is expected to go.  A hint never changes what
        # the program computes.
        self.hint = hint


class WhileStmt:
    """While loop.

    var_name, when set, names a variable bound to the condition's value
    at the start of every iteration, as `while e := next()` does.  The
    bound value is then what decides whether the body runs.
    """

    def __init__(self, cond, body, var_name: str | None = None,
                 var_type: str | None = None, var_is_mut: bool = False):
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
                 ret_unit=None):
        self.name = name
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
        # "hot" or "cold" from an annotation, saying how often the
        # function is expected to run.  A hint never changes what the
        # function computes.
        self.hint = hint
        # The unit the return type states, or None where it states none.
        self.ret_unit = ret_unit


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

    def __init__(self, expr):
        self.expr = expr


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
    """

    def __init__(self, vars, iterables, body, is_comptime: bool = False):
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

    def __init__(self, params: list[tuple[str, str]], captures: list[str] | None,
                 ret_type: str, body):
        self.params = params
        self.captures = captures
        self.ret_type = ret_type
        self.body = body


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
    """Type alias definition at top level: type NAME = TARGET [DESCRIPTION]."""

    def __init__(self, name: str, target: str, description: str | None = None):
        self.name = name
        self.target = target
        self.description = description


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


class UnitDef:
    """Top-level unit definition: unit name = formula."""

    def __init__(self, name: str, formula):
        self.name = name
        self.formula = formula


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

    def __init__(self, name: str, fields: list[tuple[str, str]],
                 repr_kind: str | None = None):
        self.name = name
        self.fields = fields
        self.repr_kind = repr_kind
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
    """Constructor for a failed result: ∄(expr)."""

    def __init__(self, value):
        self.value = value


class MatchArm:
    """One arm of a match: a pattern and the statements it guards.

    kind is "some" (∃(name), binding the contained value), "err"
    (∄(name)), "none" (∅), "type" (Type(name), one alternative of a sum
    type), or "wildcard" (_).  name is the bound name, set for every
    kind that binds; type_name is set only for "type".
    """

    def __init__(self, kind: str, name: str | None, body,
                 type_name: str | None = None):
        self.kind = kind
        self.name = name
        self.body = body
        self.type_name = type_name


class MatchStmt:
    """match subject: arms — dispatch on the shape of a value."""

    def __init__(self, subject, arms: list[MatchArm]):
        self.subject = subject
        self.arms = arms
