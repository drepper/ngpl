"""Abstract Syntax Tree nodes for the newlang language.

Each class represents one construct in the source language. The parser builds
a tree of these nodes; the evaluator walks the tree to produce results.
"""


class IntLit:
    """Integer literal with an optional bit-width suffix."""

    def __init__(self, value: int, width: str = "int"):
        self.value = value
        self.width = width


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


class BinOp:
    """Binary operator: + - * / == != < > <= >= and or."""

    def __init__(self, op: str, left, right):
        self.op = op  # one of "+", "-", "*", "/", "==", "!=", "<", ">", "<=", ">=", "and", "or"
        self.left = left
        self.right = right


class UnaryOp:
    """Unary operator: - (negation), not, opt.is_none."""

    def __init__(self, op: str, operand):
        self.op = op  # "-", "not", "is_none"
        self.operand = operand


class IfStmt:
    """Conditional statement.

    cons: the true branch (list of statements)
    alt:  the false/elif branches, each a tuple (condition_stmts, body_stmts)
          or None for a plain else without a new condition
    """

    def __init__(self, cond, cons, alt=None):
        self.cond = cond       # expression
        self.cons = cons       # list of statements
        self.alt = alt         # tuple (cond, cons, rest) or None


class WhileStmt:
    """While loop."""

    def __init__(self, cond, body):
        self.cond = cond
        self.body = body


class ReturnStmt:
    """Return statement with an optional expression."""

    def __init__(self, value=None):
        self.value = value  # expression or None


class FuncDef:
    """Function definition at top level.

    name:      function identifier
    params:    list of (name, type_annotation_or_None) tuples
    ret_type:  declared return type string, or None for implicit none
    body:      list of statements
    is_start:  True if annotated with @start
    """

    def __init__(self, name, params, ret_type, body, is_start=False,
                 is_test=False, test_refs=None,
                 expect_annotations: list[tuple[str, str]] | None = None):
        self.name = name
        self.params = params
        self.ret_type = ret_type
        self.body = body
        self.is_start = is_start
        self.is_test = is_test
        self.test_refs: list[str] = test_refs or []
        self.expect_annotations: list[tuple[str, str]] = expect_annotations or []


class VarDef:
    """Variable definition with initializer."""

    def __init__(self, name, type_annotation, init_expr, is_const: bool = False):
        self.name = name
        self.type_annotation = type_annotation  # type string or None
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
    """Subscript access: obj[index_expr]."""

    def __init__(self, obj, index):
        self.obj = obj       # any expression node (VarRef, GetAttr, Subscript)
        self.index = index   # an expression AST node for the index


class SliceAccess:
    """Slice access: obj[start…end] (inclusive on both ends)."""

    def __init__(self, obj, start, end):
        self.obj = obj
        self.start = start
        self.end = end


class TryUnwrap:
    """Postfix ? operator: unwrap optional or propagate none."""

    def __init__(self, expr):
        self.expr = expr


class ArrayAlloc:
    """Array allocation: new type[size] or var name : type[size] = init."""

    def __init__(self, element_type, size_expr, init_expr=None):
        self.element_type = element_type  # type string like "i32", "u64"
        self.size_expr = size_expr        # expression AST node for the count
        self.init_expr = init_expr        # optional per-element initializer


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

    def __init__(self, vars, iterables, body):
        self.vars = vars
        self.iterables = iterables
        self.body = body


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
