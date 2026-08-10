"""Evaluator (interpreter) for the NGPL language.

Walks the AST produced by the parser and executes it, maintaining an
environment that maps variable names to runtime values.

The evaluator handles:
- All expression types (literals, variables, binary/unary ops, function calls,
  optional construction/deconstruction, attribute access)
- All statement types (variable definitions, if/while/return, expression statements)
- Built-in runtime functions (fs.cwd, heap.alloc, sha256, format, get_stdout, etc.)

Designed as a prototype interpreter: correctness takes priority over performance.
JIT compilation and optimization are future work.
"""

import re

from interp.ast import (
    IntLit, FloatLit, StrLit, BoolLit, NoneLit, VarRef, BinOp, UnaryOp,
    IfStmt, WhileStmt, ReturnStmt, FuncDef, VarDef, ExprStmt,
    FuncCall, MethodCall, OptSome, GetAttr,
    ArrayLit, Subscript, SliceAccess, MultiSlice, ArrayAlloc, TryUnwrap,
    DropUnitExpr,
    RangeExpr, ForEachStmt, ExpectStmt, WrapExpr, LambdaExpr, SumTypeDef,
    ReshapeExpr, TupleLit, CatchStmt, EnumerateExpr,
    StaticAssert, StaticAssertEq, TypeOfExpr, ResultOfExpr, SizeOfExpr, FoldExpr,
    UnitExpr, UnitOfExpr, UnitRefExpr, RefExpr, BorrowExpr, TypeDef,
    MatchStmt, ExpErr,
    StructLit,
)
from interp.value import (
    Value, IntValue, FloatValue, StrValue, BoolValue, NoneValue, SomeValue, ExpectedValue,
    FuncValue, LambdaValue, BuiltinFunc, ObjectValue, BuiltinBoundMethod,
    ArrayValue, TupleValue, EnumType, EnumValue, RangeValue, TypeValue, UnitOfValue,
    StructType, StructInstance,
    mk_int, mk_int_wrap, mk_str, mk_bool, mk_float, none, some, is_none, is_some,
    resolve_width, resolve_float_width, wrap_int, coerce_to_type, coerce_arg,
    _TYPE_BITS, FLOAT_TYPES, FAST_TYPES,
    _split_optional_type, _parse_array_type, MAX_TENSOR_RANK, array_shape,
    format_shape,
    is_generic_type, runtime_type_of, is_type_name, _is_unsigned,
    check_bootstrap_type,
    _scalar_kind_mismatch,
    UnitValue, RefValue, Reference, ElementRef, Iterator, ArrayIterator,
    deep_copy_value, register_type_alias, DISCARD_NAME,
    register_sum_type, sum_type_alternatives, sum_type_admits,
)
from interp.env import Env
from interp.std import std, DirFD, FileStream, Bytes, MmapAllocator
from interp.errors import attach_backtrace


def _nth_root_exact(n: int, degree: int) -> int | None:
    if n < 0:
        return None
    if n == 0:
        return 0
    import math
    r = round(n ** (1.0 / degree))
    for candidate in (r - 1, r, r + 1):
        if candidate >= 0 and candidate ** degree == n:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Free-variable collection for lambda validation
# ---------------------------------------------------------------------------

def _collect_refs_from_stmts(stmts) -> set[str]:
    """Collect all variable/function references from a list of statements."""
    refs: set[str] = set()
    for stmt in stmts:
        if isinstance(stmt, VarDef):
            refs |= _collect_refs(stmt.init_expr)
        elif isinstance(stmt, ExprStmt):
            refs |= _collect_refs(stmt.expr)
        elif isinstance(stmt, ReturnStmt):
            refs |= _collect_refs(stmt.value)
        elif isinstance(stmt, IfStmt):
            refs |= _collect_refs(stmt.cond)
            refs |= _collect_refs_from_stmts(stmt.cons)
            alt = stmt.alt
            while alt is not None:
                if len(alt) == 3:
                    refs |= _collect_refs(alt[0])
                    refs |= _collect_refs_from_stmts(alt[1])
                    alt = alt[2]
                else:
                    if alt[0] is not None:
                        refs |= _collect_refs(alt[0])
                    refs |= _collect_refs_from_stmts(alt[1])
                    break
        elif isinstance(stmt, WhileStmt):
            refs |= _collect_refs(stmt.cond)
            refs |= _collect_refs_from_stmts(stmt.body)
        elif isinstance(stmt, ForEachStmt):
            for it in stmt.iterables:
                refs |= _collect_refs(it)
            refs |= _collect_refs_from_stmts(stmt.body)
        elif isinstance(stmt, tuple) and len(stmt) == 3 and stmt[0] == "assign_stmt":
            refs |= _collect_refs(stmt[1])
            refs |= _collect_refs(stmt[2])
        elif isinstance(stmt, CatchStmt):
            refs |= _collect_refs_from_stmts(stmt.body)
    return refs


def _collect_refs(node) -> set[str]:
    """Collect all variable and function names referenced in an AST expression."""
    if node is None:
        return set()
    refs: set[str] = set()
    if isinstance(node, VarRef):
        refs.add(node.name)
    elif isinstance(node, BinOp):
        refs |= _collect_refs(node.left)
        refs |= _collect_refs(node.right)
    elif isinstance(node, UnaryOp):
        refs |= _collect_refs(node.operand)
    elif isinstance(node, FuncCall):
        refs.add(node.name)
        for a in node.args:
            refs |= _collect_refs(a)
    elif isinstance(node, MethodCall):
        refs |= _collect_refs(node.obj)
        for a in node.args:
            refs |= _collect_refs(a)
    elif isinstance(node, GetAttr):
        refs |= _collect_refs(node.obj)
    elif isinstance(node, OptSome):
        refs |= _collect_refs(node.value)
    elif isinstance(node, TryUnwrap):
        refs |= _collect_refs(node.expr)
    elif isinstance(node, Subscript):
        refs |= _collect_refs(node.obj)
        for idx in node.indices:
            refs |= _collect_refs(idx)
    elif isinstance(node, SliceAccess):
        refs |= _collect_refs(node.obj)
        refs |= _collect_refs(node.start)
        refs |= _collect_refs(node.end)
    elif isinstance(node, ArrayLit):
        for e in node.elements:
            refs |= _collect_refs(e)
    elif isinstance(node, ArrayAlloc):
        refs |= _collect_refs(node.size_expr)
        for d in node.rest_dims:
            refs |= _collect_refs(d)
        if node.init_expr:
            refs |= _collect_refs(node.init_expr)
    elif isinstance(node, RangeExpr):
        refs |= _collect_refs(node.start)
        refs |= _collect_refs(node.end)
        if node.step is not None:
            refs |= _collect_refs(node.step)
    elif isinstance(node, WrapExpr):
        refs |= _collect_refs(node.expr)
    elif isinstance(node, LambdaExpr):
        if isinstance(node.body, list):
            inner = _collect_refs_from_stmts(node.body)
        else:
            inner = _collect_refs(node.body)
        inner -= {p[0] for p in node.params}
        if node.captures:
            inner -= set(node.captures)
        refs |= inner
    elif isinstance(node, ReshapeExpr):
        refs |= _collect_refs(node.shape)
        refs |= _collect_refs(node.data)
    elif isinstance(node, EnumerateExpr):
        refs |= _collect_refs(node.expr)
    elif isinstance(node, TypeOfExpr):
        refs |= _collect_refs(node.expr)
    elif isinstance(node, SizeOfExpr):
        refs |= _collect_refs(node.expr)
    elif isinstance(node, ResultOfExpr):
        refs.add(node.name)
    elif isinstance(node, TupleLit):
        for e in node.elements:
            refs |= _collect_refs(e)
    elif isinstance(node, FoldExpr):
        refs |= _collect_refs(node.func)
        refs |= _collect_refs(node.container)
        refs |= _collect_refs(node.init)
    elif isinstance(node, UnitExpr):
        refs |= _collect_refs(node.expr)
    elif isinstance(node, UnitOfExpr):
        refs |= _collect_refs(node.expr)
    elif isinstance(node, StructLit):
        refs.add(node.name)
        for _, expr in node.field_inits:
            refs |= _collect_refs(expr)
    return refs


def _as_type_value(value):
    """Bring a named type to the type value that stands for it.

    A struct or enum name evaluates to the type itself, since the name
    is also how a program reaches its members.  Where a type is being
    compared, that is the same thing `@typeof` reports.
    """
    if isinstance(value, (StructType, EnumType)):
        return TypeValue(value.name)
    return value


def _is_const_expr(node) -> bool:
    """Check whether an AST node is a compile-time constant expression."""
    if isinstance(node, (IntLit, FloatLit, StrLit, BoolLit, NoneLit)):
        return True
    if isinstance(node, BinOp):
        return _is_const_expr(node.left) and _is_const_expr(node.right)
    if isinstance(node, UnaryOp):
        return _is_const_expr(node.operand)
    if isinstance(node, ArrayLit):
        return all(_is_const_expr(e) for e in node.elements)
    if isinstance(node, TupleLit):
        return all(_is_const_expr(e) for e in node.elements)
    if isinstance(node, (TypeOfExpr, ResultOfExpr, SizeOfExpr, UnitOfExpr, UnitRefExpr)):
        return True
    # A type name stands for its type, which is as constant as a literal.
    if isinstance(node, VarRef) and is_type_name(node.name):
        return True
    if isinstance(node, UnitExpr):
        return _is_const_expr(node.expr)
    return False


def _is_comptime_expr(node, comptime_vars: set[str]) -> bool:
    """Check whether an AST node is evaluable at compile time.

    Like _is_const_expr but also allows references to compile-time
    variables (pack parameters, comptime foreach loop variables).
    """
    if _is_const_expr(node):
        return True
    if isinstance(node, VarRef) and node.name in comptime_vars:
        return True
    return False


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def unwrap_optional(value):
    """Unwrap an optional or expected value for comparison/conversion.

    SomeValue → inner value.
    ExpectedValue with ok → inner value.
    ExpectedValue with err → raises TypeError with the error description.
    Everything else → returned as-is.
    """
    if isinstance(value, SomeValue):
        return unwrap_optional(value.value)
    if isinstance(value, ExpectedValue):
        if value.is_ok():
            return value.ok_value
        raise TypeError(
            f"unwrap of expected error: {value.err_value.display()}")
    # A reference stands for what it points at wherever a value is
    # wanted; only assignment and @typeof look at the reference itself.
    if isinstance(value, Reference):
        return value.get()
    return value


def _unwrap_operand(value):
    v = unwrap_optional(value)
    if isinstance(v, UnitValue):
        return v.inner
    return v


def to_bool(value):
    """Convert a runtime Value to Python bool for control flow."""
    if isinstance(value, UnitValue):
        return to_bool(value.inner)
    if isinstance(value, BoolValue):
        return value.value
    if isinstance(value, IntValue):
        return value.value != 0
    if isinstance(value, FloatValue):
        return value.value != 0.0
    if isinstance(value, StrValue):
        return len(value.value) > 0
    if isinstance(value, NoneValue):
        return False
    if isinstance(value, SomeValue):
        return True
    if isinstance(value, ExpectedValue):
        return value.is_ok()
    # ObjectValue (DirFD, File, etc.) → always truthy.
    if isinstance(value, ObjectValue):
        return True
    return bool(value)


# ---------------------------------------------------------------------------
# Builtin function dispatchers
# ---------------------------------------------------------------------------

def _builtin_fs_cwd(args):
    """fs.cwd() — open current directory as DirFD."""
    if len(args) != 0:
        raise TypeError("fs.cwd() takes no arguments")
    dir_fd = std.fs.cwd()
    return ObjectValue(dir_fd)


def _builtin_dir_open_file(args):
    """dir.open_file(name, mode?, flags?) — open file relative to directory."""
    if len(args) < 1 or len(args) > 3:
        raise TypeError("dir.open_file(name, mode?, flags?) takes 1-3 arguments")
    dir_fd = args[0]
    if isinstance(dir_fd, ObjectValue):
        dir_fd = dir_fd.obj
    name_arg = unwrap_optional(args[1])
    if not isinstance(name_arg, StrValue):
        raise TypeError(f"open_file expects string for name, got {type(name_arg).__name__}")
    mode = None
    flags = None
    if len(args) > 2:
        mode_arg = unwrap_optional(args[2])
        if isinstance(mode_arg, IntValue):
            mode = mode_arg.value
    if len(args) > 3:
        flags_arg = unwrap_optional(args[3])
        if isinstance(flags_arg, IntValue):
            flags = flags_arg.value
    file_stream = dir_fd.open_file(name_arg.value, mode, flags)
    return ObjectValue(file_stream)


def _builtin_file_read(args):
    """file.read_file(allocator) — read entire file into allocated memory."""
    if len(args) != 1:
        raise TypeError("file.read_file(allocator) takes exactly 1 argument")
    file_stream = args[0]
    if isinstance(file_stream, ObjectValue):
        file_stream = file_stream.obj
    allocator = args[1]
    if isinstance(allocator, ObjectValue):
        allocator = allocator.obj
    result = file_stream.read_file(allocator)
    return ObjectValue(result)


def _builtin_heap_alloc(args):
    """heap.allocator() — get the global allocator."""
    if len(args) != 0:
        raise TypeError("heap.allocator() takes no arguments")
    return ObjectValue(std.get_allocator())


def _builtin_sha256(args):
    """sha256(data) — compute SHA-256 hash as arbitrary-width integer.

    The data argument can be a Bytes object (from file.read_file) or a StrValue.
    Returns an IntValue representing the 256-bit hash.
    """
    if len(args) != 1:
        raise TypeError("sha256(data) takes exactly 1 argument")
    data_arg = unwrap_optional(args[0])
    if isinstance(data_arg, ObjectValue):
        if isinstance(data_arg.obj, Bytes):
            data = bytes(data_arg.obj.data)
        else:
            raise TypeError(f"sha256 expects Bytes or StrValue, got {type(data_arg.obj).__name__}")
    elif isinstance(data_arg, StrValue):
        data = data_arg.value.encode("utf-8")
    else:
        raise TypeError(f"sha256 expects Bytes or StrValue, got {type(data_arg).__name__}")
    h = std._sha256(data)
    return mk_int(h)


def _builtin_format(args):
    """format(str, file_or_fd?, ...) → print to file if provided, else return string.

    Args:
        args[0]: StrValue — the format template.
        args[1] (optional): File object or int fd for output destination.
        args[2:] (optional): additional values to include.

    If a file/fd is provided, the formatted string is written to it and returned.
    Otherwise, the string is returned as-is.
    """
    if len(args) < 1:
        raise TypeError("format(str, file?, ...) takes at least 1 argument")
    template = args[0]
    out_file_or_fd = args[1] if len(args) > 1 else None

    # Build the format string from remaining arguments.
    def _fmt_val(v):
        """Format a single value for the output string."""
        uv = unwrap_optional(v)
        if isinstance(uv, IntValue):
            # Large integers (e.g., hashes) formatted as hex; small ones as decimal.
            if uv.value.bit_length() > 32 or uv.value < 0:
                return format(uv.value, "x")
            return str(uv.value)
        if isinstance(uv, StrValue):
            return uv.value
        if isinstance(uv, BoolValue):
            return "true" if uv.value else "false"
        if is_none(uv):
            return "\N{EMPTY SET}"
        if isinstance(uv, SomeValue):
            inner = unwrap_optional(uv)
            return f"some({inner.display()})"
        if isinstance(uv, ObjectValue):
            obj = uv.obj
            if isinstance(obj, Bytes):
                return f"<bytes {len(obj.data)}>"
            return f"<{type(obj).__name__}>"
        return str(uv)

    parts = [_fmt_val(template)]
    for arg in args[2:]:
        parts.append(_fmt_val(arg))

    result_str = "".join(parts) + "\n"

    # Write to file if provided.
    if out_file_or_fd is not None:
        out_obj = unwrap_optional(out_file_or_fd)
        fd = 1  # default to stdout
        if isinstance(out_obj, ObjectValue):
            out_obj = out_obj.obj
        if isinstance(out_obj, int):
            fd = out_obj
        elif isinstance(out_obj, FileStream):
            fd = out_obj._fd
        data = result_str.encode("utf-8")
        os_write(fd, data)
    return mk_str(result_str)


def _builtin_get_stdout(args):
    """get_stdout() → StdoutFile wrapped as ObjectValue."""
    if len(args) != 0:
        raise TypeError("get_stdout() takes no arguments")
    return ObjectValue(std._stdout_file)


def _builtin_hash_to_hex(args):
    """Convert an IntValue hash to a hex string.

    Usage: hash_int.to_hex() via a method call on the IntValue.
    But since we don't have methods on values yet, we provide it as a builtin
    that's called from the evaluator when encountering certain patterns.

    Actually, let's handle this through a helper in the evaluator.
    """
    if len(args) != 1:
        raise TypeError("hash_to_hex(value) takes exactly 1 argument")
    value = unwrap_optional(args[0])
    if isinstance(value, IntValue):
        return mk_str(format(value.value, "x"))
    raise TypeError(f"hash_to_hex expects int, got {type(value).__name__}")


def os_write(fd, data: bytes):
    """Write bytes to a file descriptor (thin wrapper around os.write)."""
    try:
        return os.write(fd, data)
    except OSError as e:
        raise OSError(f"write(fd={fd}): {e}")


# ---------------------------------------------------------------------------
# Generic type resolution helpers
# ---------------------------------------------------------------------------


def _extract_generic_name(type_str: str) -> str | None:
    """Extract the generic type variable name from a type string.

    Strips optional (?) and array ([]) suffixes to find the base name.
    Returns the generic name (e.g., "T\N{APOSTROPHE}") or None if not generic.
    """
    base = type_str
    qpos = base.find("?")
    if qpos >= 0:
        base = base[:qpos]
    if base.endswith("[]"):
        base = base[:-2]
    if base.endswith("\N{APOSTROPHE}") and len(base) > 1:
        return base
    return None


def _resolve_concrete_for_generic(param_type: str, arg: Value) -> str:
    """Determine the concrete type a generic parameter binds to from an argument.

    For T\N{APOSTROPHE}[] parameters, extracts the element type from array arguments.
    For plain T\N{APOSTROPHE} parameters, returns the runtime type of the argument.
    """
    base = param_type
    qpos = base.find("?")
    if qpos >= 0:
        base = base[:qpos]

    actual = arg
    if isinstance(actual, SomeValue):
        actual = actual.value

    if base.endswith("[]"):
        generic_base = base[:-2]
        if generic_base.endswith("\N{APOSTROPHE}"):
            if isinstance(actual, ObjectValue) and isinstance(actual.obj, ArrayValue):
                return actual.obj.element_type or "int"

    return runtime_type_of(actual)


def _substitute_generics(type_str: str, generic_map: dict[str, str]) -> str:
    """Replace generic type names in a type string with their concrete bindings."""
    result = type_str
    for generic, concrete in generic_map.items():
        result = result.replace(generic, concrete)
    return result


# ---------------------------------------------------------------------------
# Main evaluator
# ---------------------------------------------------------------------------


# The array member functions, mapped to how many arguments each takes.
# Modelled on Rust's Vec: push/pop at the end, insert/remove at an index,
# and get for a bounds-checked read.
# The array methods that change the array rather than only reading it.
_ARRAY_MUTATORS = frozenset({"push", "pop", "insert", "remove"})

_ARRAY_METHODS: dict[str, int] = {
    "push": 1,
    "pop": 0,
    "insert": 2,
    "remove": 1,
    "get": 1,
    "iterate": 0,
}


class Evaluator:
    """Evaluates NGPL AST in a given environment.

    The evaluator maintains an environment (Env) for variable lookups and
    provides methods to evaluate expressions and statements.
    """

    def __init__(self, env=None, test_hooks: dict[str, list] | None = None):
        self.env = env or Env()
        self._test_hooks = test_hooks or {}
        self._tests_run: set[str] = set()
        self._current_ret_type: str | None = None
        self._frozen_vars: dict[str, str] = {}
        self._warnings: list[str] = []
        self._wrapping: bool = False
        self._catch_depth: int = 0
        self._pure_func_name: str | None = None
        self._generic_map: dict[str, str] = {}
        self._comptime_vars: set[str] = set()
        self._last_pos: tuple[int, int, int | None] | None = None
        # One entry per active call to a user-defined function, outermost
        # first.  Each is a mutable [name, position] pair whose position
        # tracks the statement currently executing in that frame, so an
        # unwound stack still says where each caller had got to.
        self._call_stack: list[list] = []
        # Resources produced by the statement currently running, so that
        # any the statement does not keep can be released as it ends.
        self._temporaries: list | None = None
        # Pre-compute builtin function mappings (avoid repeated lookups).
        self._ops = {
            "+": self._op_add,
            "-": self._op_sub,
            "\N{MULTIPLICATION SIGN}": self._op_mul,
            "/": self._op_div,
            "%": self._op_mod,
            "==": self._op_eq,
            "!=": self._op_neq,
            "<": self._op_lt,
            ">": self._op_gt,
            "<=": self._op_lte,
            ">=": self._op_gte,
            "and": self._op_and,
            "or": self._op_or,
            # Bitwise operators for algorithms like SHA-256.
            "<<": self._op_lshift,
            ">>": self._op_rshift,
            "&": self._op_bitand,
            "^": self._op_bitxor,
            "|": self._op_bitor,
            "«": self._op_lshift,
            "»": self._op_rshift,
            "↺": self._op_rotl,
            "↻": self._op_rotr,
            "∧": self._op_logic_and,
            "∨": self._op_logic_or,
            "⊕": self._op_logic_xor,
            "⊼": self._op_logic_nand,
            "⊽": self._op_logic_nor,
            "\N{UPWARDS ARROW}": self._op_pow,
        }

    # ------------------------------------------------------------------
    # Binary operators
    # ------------------------------------------------------------------

    def _op_add(self, left, right):
        """Addition: integers, floats, and strings (concatenation)."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return self._mk_int(lu.value + ru.value, resolve_width(lu.width, ru.width))
        ff = self._require_matching_numeric(lu, ru, "addition")
        if ff is not None:
            return mk_float(ff[0] + ff[1], ff[2])
        if isinstance(lu, StrValue) and isinstance(ru, StrValue):
            return mk_str(lu.value + ru.value)
        raise TypeError(f"addition expected int+int, float+float, or str+str, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_sub(self, left, right):
        """Subtraction."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return self._mk_int(lu.value - ru.value, resolve_width(lu.width, ru.width))
        ff = self._require_matching_numeric(lu, ru, "subtraction")
        if ff is not None:
            return mk_float(ff[0] - ff[1], ff[2])
        raise TypeError(f"subtraction expected int+int or float+float, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_mul(self, left, right):
        """Multiplication."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return self._mk_int(lu.value * ru.value, resolve_width(lu.width, ru.width))
        ff = self._require_matching_numeric(lu, ru, "multiplication")
        if ff is not None:
            return mk_float(ff[0] * ff[1], ff[2])
        raise TypeError(f"multiplication expected int+int or float+float, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_div(self, left, right):
        """Division: integer (truncates toward zero, returns ExpectedValue) or float."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            if ru.value == 0:
                return self._division_error()
            result = int(lu.value / ru.value) if lu.value * ru.value >= 0 else -int(abs(lu.value) / abs(ru.value))
            return ExpectedValue.ok(self._mk_int(result, resolve_width(lu.width, ru.width)))
        ff = self._require_matching_numeric(lu, ru, "division")
        if ff is not None:
            if ff[1] == 0.0:
                return self._division_error()
            return mk_float(ff[0] / ff[1], ff[2])
        raise TypeError(f"division expected int+int or float+float, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_mod(self, left, right):
        """Remainder (truncation toward zero): a % b = a - trunc(a/b)*b.  Returns ExpectedValue."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            if ru.value == 0:
                return self._division_error()
            quot = int(lu.value / ru.value) if lu.value * ru.value >= 0 else -int(abs(lu.value) / abs(ru.value))
            return ExpectedValue.ok(self._mk_int(lu.value - quot * ru.value, resolve_width(lu.width, ru.width)))
        ff = self._require_matching_numeric(lu, ru, "remainder")
        if ff is not None:
            import math
            if ff[1] == 0.0:
                return self._division_error()
            return mk_float(math.fmod(ff[0], ff[1]), ff[2])
        raise TypeError(f"remainder expected int+int or float+float, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_pow(self, left, right):
        """Exponentiation: int↑int, float↑float, or float↑int."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            if ru.value < 0:
                raise TypeError("integer exponentiation requires non-negative exponent")
            return self._mk_int(lu.value ** ru.value, lu.width)
        if isinstance(lu, FloatValue) and isinstance(ru, FloatValue):
            return mk_float(lu.value ** ru.value, resolve_float_width(lu.width, ru.width))
        if isinstance(lu, FloatValue) and isinstance(ru, IntValue):
            return mk_float(lu.value ** ru.value, lu.width)
        if isinstance(lu, IntValue) and isinstance(ru, FloatValue):
            raise TypeError(
                f"exponentiation requires matching types, got {lu.width} and {ru.width}")
        raise TypeError(
            f"exponentiation expected numeric operands, "
            f"got {type(lu).__name__} and {type(ru).__name__}")

    @staticmethod
    def _reject_mixed_optional(left, right, what: str):
        """Reject comparing an optional against a plain value.

        An optional and the value it may hold are different things, and
        an equality that quietly looked through the optional would make
        `it.next() == 97` read as a test of the element when it is
        really a test of the element *and* of there being one at all.
        """
        left_opt = isinstance(left, (SomeValue, NoneValue))
        right_opt = isinstance(right, (SomeValue, NoneValue))
        if left_opt == right_opt:
            return
        raise TypeError(
            f"{what}: cannot compare an optional with a plain value; write "
            f"\N{THERE EXISTS}(v) to compare against a present value, "
            f"\N{EMPTY SET} against an absent one, or ?? to supply a default")

    def _op_eq(self, left, right):
        """Equality comparison."""
        self._reject_mixed_optional(left, right, "==")
        # Two optionals are compared by shape first and contents second,
        # so that a present-but-empty optional and an absent one are
        # told apart: ∃(∅) is not ∅.
        if isinstance(left, (SomeValue, NoneValue)):
            left_present = isinstance(left, SomeValue)
            right_present = isinstance(right, SomeValue)
            if left_present != right_present:
                return mk_bool(False)
            if not left_present:
                return mk_bool(True)
            return self._op_eq(left.value, right.value)
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        # ∅ equals itself and nothing else.  Without this the fall-through
        # below reports every comparison against ∅ as unequal, including
        # ∅ == ∅, which makes `while e != ∅` loop for ever.
        if isinstance(lu, NoneValue) or isinstance(ru, NoneValue):
            return mk_bool(isinstance(lu, NoneValue) and isinstance(ru, NoneValue))
        if isinstance(lu, EnumValue) and isinstance(ru, EnumValue):
            if lu.enum_type is not ru.enum_type:
                raise TypeError(
                    f"cannot compare enum '{lu.enum_type.name}' "
                    f"with enum '{ru.enum_type.name}'")
            return mk_bool(lu.value == ru.value)
        if isinstance(lu, EnumValue) and isinstance(ru, IntValue):
            return mk_bool(lu.value == ru.value)
        if isinstance(lu, IntValue) and isinstance(ru, EnumValue):
            return mk_bool(lu.value == ru.value)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_bool(lu.value == ru.value)
        if isinstance(lu, FloatValue) and isinstance(ru, FloatValue):
            return mk_bool(lu.value == ru.value)
        if isinstance(lu, (IntValue, FloatValue)) and isinstance(ru, (IntValue, FloatValue)):
            lv = lu.value if isinstance(lu, FloatValue) else float(lu.value)
            rv = ru.value if isinstance(ru, FloatValue) else float(ru.value)
            return mk_bool(lv == rv)
        if isinstance(lu, StrValue) and isinstance(ru, StrValue):
            return mk_bool(lu.value == ru.value)
        if isinstance(lu, BoolValue) and isinstance(ru, BoolValue):
            return mk_bool(lu.value == ru.value)
        if isinstance(lu, TypeValue) and isinstance(ru, TypeValue):
            return mk_bool(lu.name == ru.name)
        if isinstance(lu, UnitOfValue) and isinstance(ru, UnitOfValue):
            if lu.unit is None and ru.unit is None:
                return mk_bool(True)
            if lu.unit is None or ru.unit is None:
                return mk_bool(False)
            return mk_bool(lu.unit.same_dimension(ru.unit)
                           and lu.unit.factor == ru.unit.factor)
        if type(lu) != type(ru):
            return mk_bool(False)
        return mk_bool(False)

    def _op_neq(self, left, right):
        """Inequality comparison."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        eq = self._op_eq(left, right)
        return mk_bool(not eq.value)

    def _op_lt(self, left, right):
        """Less-than comparison."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_bool(lu.value < ru.value)
        lf, rf, _ = self._promote_to_float(lu, ru)
        if lf is not None:
            return mk_bool(lf < rf)
        raise TypeError(f"less-than expected numeric types, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_gt(self, left, right):
        """Greater-than comparison."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_bool(lu.value > ru.value)
        lf, rf, _ = self._promote_to_float(lu, ru)
        if lf is not None:
            return mk_bool(lf > rf)
        raise TypeError(f"greater-than expected numeric types, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_lte(self, left, right):
        """Less-than-or-equal comparison."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_bool(lu.value <= ru.value)
        lf, rf, _ = self._promote_to_float(lu, ru)
        if lf is not None:
            return mk_bool(lf <= rf)
        raise TypeError(f"less-equal expected numeric types, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_gte(self, left, right):
        """Greater-than-or-equal comparison."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_bool(lu.value >= ru.value)
        lf, rf, _ = self._promote_to_float(lu, ru)
        if lf is not None:
            return mk_bool(lf >= rf)
        raise TypeError(f"greater-equal expected numeric types, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_and(self, left, right):
        """Short-circuit boolean and."""
        lu = _unwrap_operand(left)
        if not to_bool(lu):
            return mk_bool(False)
        ru = _unwrap_operand(right)
        return mk_bool(to_bool(ru))

    def _op_or(self, left, right):
        """Short-circuit boolean or."""
        lu = _unwrap_operand(left)
        if to_bool(lu):
            return mk_bool(True)
        ru = _unwrap_operand(right)
        return mk_bool(to_bool(ru))

    def _op_lshift(self, left, right):
        """Left shift: int << int."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            width, err = self._shift_result_width(lu, ru)
            if err is not None:
                return err
            return mk_int_wrap(lu.value << ru.value, width)
        raise TypeError(f"left-shift expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_rshift(self, left, right):
        """Logical right shift: int >> int.

        For typed unsigned integers, the value is already non-negative so
        Python's >> produces the correct logical shift.  mk_int wraps the
        result to the type's range.
        """
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            width, err = self._shift_result_width(lu, ru)
            if err is not None:
                return err
            val = wrap_int(lu.value, lu.width)
            return mk_int_wrap(val >> ru.value, width)
        raise TypeError(f"right-shift expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_bitand(self, left, right):
        """Bitwise AND: int & int or flag_enum & flag_enum."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, EnumValue) and isinstance(ru, EnumValue):
            if lu.enum_type is not ru.enum_type:
                raise TypeError(
                    f"cannot combine enum '{lu.enum_type.name}' with '{ru.enum_type.name}'")
            if not lu.enum_type.is_flag:
                raise TypeError(f"bitwise operations require @flag enum, got '{lu.enum_type.name}'")
            return EnumValue(lu.enum_type, lu.value & ru.value)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_int_wrap(lu.value & ru.value, resolve_width(lu.width, ru.width))
        raise TypeError(f"bitwise-and expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_bitxor(self, left, right):
        """Bitwise XOR: int ^ int or flag_enum ^ flag_enum."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, EnumValue) and isinstance(ru, EnumValue):
            if lu.enum_type is not ru.enum_type:
                raise TypeError(
                    f"cannot combine enum '{lu.enum_type.name}' with '{ru.enum_type.name}'")
            if not lu.enum_type.is_flag:
                raise TypeError(f"bitwise operations require @flag enum, got '{lu.enum_type.name}'")
            return EnumValue(lu.enum_type, lu.value ^ ru.value)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_int_wrap(lu.value ^ ru.value, resolve_width(lu.width, ru.width))
        raise TypeError(f"bitwise-xor expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_bitor(self, left, right):
        """Bitwise OR: int | int or flag_enum | flag_enum."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, EnumValue) and isinstance(ru, EnumValue):
            if lu.enum_type is not ru.enum_type:
                raise TypeError(
                    f"cannot combine enum '{lu.enum_type.name}' with '{ru.enum_type.name}'")
            if not lu.enum_type.is_flag:
                raise TypeError(f"bitwise operations require @flag enum, got '{lu.enum_type.name}'")
            return EnumValue(lu.enum_type, lu.value | ru.value)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_int_wrap(lu.value | ru.value, resolve_width(lu.width, ru.width))
        raise TypeError(f"bitwise-or expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_rotl(self, left, right):
        """Rotate left within the operand's bit width (default 32)."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            w = resolve_width(lu.width, ru.width)
            bits = _TYPE_BITS.get(w, 32)
            mask = (1 << bits) - 1
            n = ru.value & (bits - 1)
            val = lu.value & mask
            result = ((val << n) | (val >> (bits - n))) & mask
            return mk_int_wrap(result, w)
        raise TypeError(f"rotate-left expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_rotr(self, left, right):
        """Rotate right within the operand's bit width (default 32)."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            w = resolve_width(lu.width, ru.width)
            bits = _TYPE_BITS.get(w, 32)
            mask = (1 << bits) - 1
            n = ru.value & (bits - 1)
            val = lu.value & mask
            result = ((val >> n) | (val << (bits - n))) & mask
            return mk_int_wrap(result, w)
        raise TypeError(f"rotate-right expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    @staticmethod
    def _logic_bool(val) -> bool:
        """Convert a value to logical boolean for binary logic operations.

        Only integers and booleans are accepted; raises TypeError otherwise.
        """
        if isinstance(val, BoolValue):
            return val.value
        if isinstance(val, IntValue):
            return val.value != 0
        raise TypeError(
            f"logic operations require integer or bool, "
            f"got {type(val).__name__}")

    def _op_logic_and(self, left, right):
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        return mk_bool(self._logic_bool(lu) and self._logic_bool(ru))

    def _op_logic_or(self, left, right):
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        return mk_bool(self._logic_bool(lu) or self._logic_bool(ru))

    def _op_logic_xor(self, left, right):
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        return mk_bool(self._logic_bool(lu) != self._logic_bool(ru))

    def _op_logic_nand(self, left, right):
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        return mk_bool(not (self._logic_bool(lu) and self._logic_bool(ru)))

    def _op_logic_nor(self, left, right):
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        return mk_bool(not (self._logic_bool(lu) or self._logic_bool(ru)))

    def _op_concat(self, left, right):
        """Concatenate arrays at the outermost dimension."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        la = self._as_array(lu)
        ra = self._as_array(ru)
        if la is None:
            raise TypeError(
                f"\N{DOUBLE PLUS}: left operand must be an array, "
                f"got {type(lu).__name__}")
        if ra is None:
            raise TypeError(
                f"\N{DOUBLE PLUS}: right operand must be an array, "
                f"got {type(ru).__name__}")
        etype = la.element_type or ra.element_type
        return ObjectValue(
            ArrayValue(la.values() + ra.values(),
                       element_type=etype))

    def _mk_int(self, value: int, width: str) -> IntValue:
        if self._wrapping:
            return mk_int_wrap(value, width)
        return mk_int(value, width)

    def _std_error(self, member: str, fallback: str) -> ExpectedValue:
        """Create an ExpectedValue.err naming a member of std.errors.

        The enum is taken from the std module itself rather than looked
        up by name: a lambda's environment does not reach the globals,
        so the lookup failed there and the error degraded to a string,
        which is not the type the return annotation promises.
        """
        errors_enum = getattr(std, "errors", None)
        if isinstance(errors_enum, EnumType):
            return ExpectedValue.err(
                EnumValue(errors_enum, errors_enum.members[member]))
        return ExpectedValue.err(mk_str(fallback))

    def _shift_result_width(self, lu, ru):
        """The width a shift produces, or an error where it has none.

        A shift moves bits within the value it is given, so the result
        is the same type: the count says how far, not what type to
        become.  A count that reaches the number of value bits would
        move every one of them out, which is a mistake rather than a
        way to write zero, so it is refused.

        A signed type has one value bit fewer than its width, since the
        top bit carries the sign rather than part of the value: an i8
        holds seven value bits, so seven is already too far.
        """
        bits = _TYPE_BITS.get(lu.width)
        if bits is not None:
            value_bits = bits if _is_unsigned(lu.width) else bits - 1
            if ru.value >= value_bits:
                return None, self._std_error(
                    "shift_out_of_range",
                    f"shift of {ru.value} on a {lu.width}, which has "
                    f"{value_bits} value bits")
        if ru.value < 0:
            return None, self._std_error(
                "shift_out_of_range", f"shift by {ru.value}")
        return lu.width, None

    def _division_error(self) -> ExpectedValue:
        """Create an ExpectedValue.err for division by zero using std.errors.

        The enum is taken from the std module itself rather than looked
        up by name: a lambda's environment does not reach the globals,
        so the lookup failed there and the error degraded to a string,
        which is not the type the return annotation promises.
        """
        errors_enum = getattr(std, "errors", None)
        if isinstance(errors_enum, EnumType):
            return ExpectedValue.err(
                EnumValue(errors_enum, errors_enum.members["division_by_zero"]))
        return ExpectedValue.err(mk_str("division by zero"))

    @staticmethod
    def _promote_to_float(lu, ru) -> tuple[float | None, float, str]:
        """Try to promote two operands to float for comparison.

        Returns (left_float, right_float, width) on success,
        or (None, 0.0, "") if neither operand is a float.

        Allows mixed int/float promotion for comparisons only.
        """
        if isinstance(lu, FloatValue) and isinstance(ru, FloatValue):
            return lu.value, ru.value, resolve_float_width(lu.width, ru.width)
        if isinstance(lu, FloatValue) and isinstance(ru, IntValue):
            return lu.value, float(ru.value), lu.width
        if isinstance(lu, IntValue) and isinstance(ru, FloatValue):
            return float(lu.value), ru.value, ru.width
        return None, 0.0, ""

    @staticmethod
    def _require_matching_numeric(lu, ru, op_name: str) -> tuple[float, float, str] | None:
        """Require both operands to be the same numeric category for arithmetic.

        Returns (left_float, right_float, width) when both are float.
        Returns None when both are int (caller handles int+int directly).
        Raises TypeError on mixed int+float.
        """
        if isinstance(lu, FloatValue) and isinstance(ru, FloatValue):
            return lu.value, ru.value, resolve_float_width(lu.width, ru.width)
        if isinstance(lu, IntValue) and isinstance(ru, FloatValue):
            raise TypeError(
                f"{op_name} requires matching types, got {lu.width} and {ru.width}")
        if isinstance(lu, FloatValue) and isinstance(ru, IntValue):
            raise TypeError(
                f"{op_name} requires matching types, got {lu.width} and {ru.width}")
        return None

    # ------------------------------------------------------------------
    # Array element-wise dispatch
    # ------------------------------------------------------------------

    @staticmethod
    def _as_array(val):
        u = unwrap_optional(val)
        if isinstance(u, ObjectValue) and isinstance(u.obj, ArrayValue):
            return u.obj
        return None

    def _apply_binop(self, op_fn, left, right):
        la = self._as_array(left)
        ra = self._as_array(right)
        if la is not None and ra is not None:
            etype = la.element_type or ra.element_type
            return ObjectValue(ArrayValue(
                [op_fn(l, r) for l, r in zip(la.values(), ra.values())],
                element_type=etype))
        if la is not None:
            return ObjectValue(ArrayValue(
                [op_fn(l, right) for l in la.values()],
                element_type=la.element_type))
        if ra is not None:
            return ObjectValue(ArrayValue(
                [op_fn(left, r) for r in ra.values()],
                element_type=ra.element_type))
        return op_fn(left, right)

    # ------------------------------------------------------------------
    # Unit-aware arithmetic
    # ------------------------------------------------------------------

    def _unit_binop(self, op: str, lu, ru):
        """Handle binary operations when one or both operands have units."""
        from fractions import Fraction
        l_is_unit = isinstance(lu, UnitValue)
        r_is_unit = isinstance(ru, UnitValue)
        l_inner = lu.inner if l_is_unit else lu
        r_inner = ru.inner if r_is_unit else ru
        l_unit = lu.unit if l_is_unit else None
        r_unit = ru.unit if r_is_unit else None

        if op in ("+", "-"):
            if l_is_unit and not r_is_unit:
                if isinstance(r_inner, IntValue) and r_inner.width != "int":
                    raise TypeError(
                        f"cannot {op} unit {l_unit.display_name} with "
                        f"typed integer {r_inner.width} without unit")
                op_fn = self._ops[op]
                return UnitValue(op_fn(l_inner, r_inner), l_unit)
            if r_is_unit and not l_is_unit:
                if isinstance(l_inner, IntValue) and l_inner.width != "int":
                    raise TypeError(
                        f"cannot {op} typed integer {l_inner.width} "
                        f"without unit with unit {r_unit.display_name}")
                op_fn = self._ops[op]
                return UnitValue(op_fn(l_inner, r_inner), r_unit)
            if not l_unit.same_dimension(r_unit):
                raise TypeError(
                    f"incompatible units for {op}: "
                    f"{l_unit.display_name} and {r_unit.display_name}")
            if l_unit == r_unit:
                op_fn = self._ops[op]
                return UnitValue(op_fn(l_inner, r_inner), l_unit)
            l_base = self._to_base_value(l_inner, l_unit)
            r_base = self._to_base_value(r_inner, r_unit)
            op_fn = self._ops[op]
            return UnitValue(op_fn(l_base, r_base), l_unit.base_form())

        if op == "\N{MULTIPLICATION SIGN}":
            result = self._ops["\N{MULTIPLICATION SIGN}"](l_inner, r_inner)
            if l_is_unit and r_is_unit:
                result_unit = l_unit * r_unit
                if result_unit.is_dimensionless():
                    return result
                return UnitValue(result, result_unit)
            return UnitValue(result, l_unit if l_is_unit else r_unit)

        if op == "/":
            result = self._ops["/"](l_inner, r_inner)
            if isinstance(result, ExpectedValue):
                if not result.is_ok():
                    return result
                result = result.ok_value
            if l_is_unit and r_is_unit:
                result_unit = l_unit / r_unit
                if result_unit.is_dimensionless():
                    return result
                return UnitValue(result, result_unit)
            runit = l_unit if l_is_unit else r_unit
            if not l_is_unit:
                from interp.units import Unit
                runit = Unit({}, Fraction(1), "1") / r_unit
            return UnitValue(result, runit)

        if op == "%":
            if l_is_unit and not r_is_unit:
                result = self._ops["%"](l_inner, r_inner)
                if isinstance(result, ExpectedValue):
                    if not result.is_ok():
                        return result
                    result = result.ok_value
                return UnitValue(result, l_unit)
            if r_is_unit and not l_is_unit:
                result = self._ops["%"](l_inner, r_inner)
                if isinstance(result, ExpectedValue):
                    if not result.is_ok():
                        return result
                    result = result.ok_value
                return UnitValue(result, r_unit)
            if not l_unit.same_dimension(r_unit):
                raise TypeError(
                    f"incompatible units for %: "
                    f"{l_unit.display_name} and {r_unit.display_name}")
            if l_unit == r_unit:
                result = self._ops["%"](l_inner, r_inner)
                result_unit = l_unit
            else:
                l_base = self._to_base_value(l_inner, l_unit)
                r_base = self._to_base_value(r_inner, r_unit)
                result = self._ops["%"](l_base, r_base)
                result_unit = l_unit.base_form()
            if isinstance(result, ExpectedValue):
                if not result.is_ok():
                    return result
                result = result.ok_value
            return UnitValue(result, result_unit)

        if op == "\N{UPWARDS ARROW}":
            if r_is_unit:
                raise TypeError("exponent cannot have a unit")
            if not l_is_unit:
                return self._ops[op](l_inner, r_inner)
            if not isinstance(r_inner, IntValue):
                raise TypeError(
                    "exponent for unit-bearing base must be an integer")
            exp = r_inner.value
            result = self._ops[op](l_inner, r_inner)
            from interp.units import Unit
            new_components = {k: v * exp for k, v in l_unit.components.items()}
            new_factor = l_unit.factor ** exp
            from interp.units import _display_from_components
            new_unit = Unit(
                new_components, new_factor,
                _display_from_components(
                    {k: v for k, v in new_components.items() if v != 0}))
            if new_unit.is_dimensionless():
                return result
            return UnitValue(result, new_unit)

        if op in ("==", "!=", "<", ">", "<=", ">="):
            if l_is_unit and not r_is_unit:
                if isinstance(r_inner, IntValue) and r_inner.width != "int":
                    raise TypeError(
                        f"cannot compare unit {l_unit.display_name} with "
                        f"typed integer {r_inner.width} without unit")
                return self._ops[op](l_inner, r_inner)
            if r_is_unit and not l_is_unit:
                if isinstance(l_inner, IntValue) and l_inner.width != "int":
                    raise TypeError(
                        f"cannot compare typed integer {l_inner.width} "
                        f"without unit with unit {r_unit.display_name}")
                return self._ops[op](l_inner, r_inner)
            if not l_unit.same_dimension(r_unit):
                raise TypeError(
                    f"incompatible units for comparison: "
                    f"{l_unit.display_name} and {r_unit.display_name}")
            if l_unit == r_unit:
                return self._ops[op](l_inner, r_inner)
            l_base = self._to_base_value(l_inner, l_unit)
            r_base = self._to_base_value(r_inner, r_unit)
            return self._ops[op](l_base, r_base)

        if op in ("<<", ">>", "«", "»", "↺", "↻",
                  "&", "|", "^", "∧", "∨", "⊕", "⊼", "⊽"):
            result = self._ops[op](l_inner, r_inner)
            unit = l_unit if l_is_unit else r_unit
            if unit is not None:
                return UnitValue(result, unit)
            return result

        raise TypeError(f"operator '{op}' not supported with units")

    def _to_base_value(self, inner, unit):
        """Convert a numeric value from its unit scale to base (factor=1)."""
        from fractions import Fraction
        if isinstance(inner, IntValue):
            result = Fraction(inner.value) * unit.factor
            if result.denominator == 1:
                return self._mk_int(int(result), inner.width)
            return mk_float(float(result))
        if isinstance(inner, FloatValue):
            return mk_float(float(Fraction(inner.value) * unit.factor), inner.width)
        return inner

    def _convert_unit_value(self, value: UnitValue, target_unit) -> UnitValue:
        """Convert a UnitValue to a target unit, checking lossless for integers."""
        from fractions import Fraction
        if not value.unit.same_dimension(target_unit):
            raise TypeError(
                f"incompatible units: {value.unit.display_name} "
                f"and {target_unit.display_name}")
        ratio = value.unit.factor / target_unit.factor
        inner = value.inner
        if isinstance(inner, IntValue):
            result = Fraction(inner.value) * ratio
            if result.denominator != 1:
                raise TypeError(
                    f"cannot convert {inner.value} "
                    f"{value.unit.display_name} to "
                    f"{target_unit.display_name} without loss "
                    f"(result is {float(result)})")
            return UnitValue(self._mk_int(int(result), inner.width), target_unit)
        if isinstance(inner, FloatValue):
            return UnitValue(
                mk_float(float(Fraction(inner.value) * ratio), inner.width),
                target_unit)
        raise TypeError(
            f"cannot convert {type(inner).__name__} with units")

    def _check_resizable_argument(self, func, param_name, param_type,
                                  arg_value):
        """Reject a fixed-size array where a resizable one is asked for.

        Only a by-reference parameter is affected.  `&mut T[]` lets the
        callee change the length of the caller's own array, which a
        fixed-size one cannot allow.  A by-value `mut T[]` takes a copy,
        and a copy handed to a dynamically-sized parameter is dynamic --
        the same conversion `let d : mut i32[] = f` performs -- so there
        is nothing to refuse.
        """
        if param_type is None or param_name not in func.param_muts:
            return
        if param_name not in func.param_refs:
            return
        array_type = _parse_array_type(param_type)
        if array_type is None or array_type[1][0] is not None:
            return  # not a parameter whose length is open
        value = arg_value
        if isinstance(value, RefValue):
            value = value.get()
        value = unwrap_optional(value)
        if not (isinstance(value, ObjectValue)
                and isinstance(value.obj, ArrayValue)):
            return
        fixed = value.obj.fixed_size
        if fixed is None:
            return
        raise TypeError(
            f"{func.name}: parameter '{param_name}' is a by-reference "
            f"mutable '{param_type}', whose length the function may change, "
            f"but the argument is a fixed-size array of {fixed} element"
            f"{'' if fixed == 1 else 's'}")

    def _check_mutating_call(self, node):
        """Reject a method that changes an array held by a `let` binding.

        push and its kin change the array as surely as writing an
        element does, so the same rule applies: a binding that cannot be
        reassigned cannot have its contents rearranged either.
        """
        base = node.obj
        while isinstance(base, (Subscript, SliceAccess, MultiSlice, GetAttr)):
            base = base.obj
        if not isinstance(base, VarRef):
            return
        name = base.name
        kind = self._frozen_vars.get(name)
        if kind == "moved":
            raise TypeError(f"use of moved value '{name}'")
        if kind is not None:
            raise TypeError(
                f"{node.method}: cannot modify {kind} variable '{name}'")
        if self.env.is_const_global(name):
            raise TypeError(
                f"{node.method}: cannot modify let variable '{name}'")

    def _call_array_method(self, array: ArrayValue, name: str, args):
        """Call one of the array's built-in member functions.

        Indices are checked for the same unit agreement that `arr[i]`
        requires, so the member functions and the subscript syntax accept
        exactly the same index expressions.

        The two operations that can fail on a well-formed program --
        asking for an element that may not be there, and taking one off
        an array that may be empty -- answer with an optional.  The two
        that indicate a mistake in the program's own bookkeeping --
        inserting or removing at an index the array does not have --
        raise instead.
        """
        arity = _ARRAY_METHODS[name]
        if len(args) != arity:
            raise TypeError(
                f"array.{name} takes {arity} argument"
                f"{'' if arity == 1 else 's'}, got {len(args)}")

        if name == "iterate":
            return ArrayIterator(array)

        if name == "push":
            array.push(unwrap_optional(args[0]))
            return none()

        if name == "pop":
            popped = array.pop()
            return none() if popped is None else some(popped)

        index = self._check_index_unit(unwrap_optional(args[0]), array)

        if name == "get":
            if 0 <= index.value < array.sizeof:
                return some(array.get(index.value))
            return none()

        if name == "insert":
            array.insert(index.value, unwrap_optional(args[1]))
            return none()

        return array.remove(index.value)

    def _callstack_value(self, args):
        """Return the interpreted program's call stack, innermost first.

        Each entry is a (name, line, column) tuple.  The frame for the
        call to callstack itself is left out, so entry 0 is always the
        function that asked.
        """
        if args:
            raise TypeError("std.callstack takes no arguments")
        frames = []
        for frame in reversed(self._call_stack):
            name, pos = frame[0], frame[1]
            line, col = (pos[0], pos[1]) if pos is not None else (0, 0)
            frames.append(TupleValue([mk_str(name), mk_int(line), mk_int(col)]))
        return ObjectValue(ArrayValue(frames))

    def _struct_offsetof(self, struct_type, args):
        """Return the byte offset of a named field within a @repr(C) struct."""
        from interp.layout import LayoutError, struct_layout, struct_lookup
        from interp.units import BUILTIN_UNITS

        if len(args) != 1:
            raise TypeError(
                f"{struct_type.name}.offsetof takes one field name")
        name = unwrap_optional(args[0])
        if not isinstance(name, StrValue):
            raise TypeError(
                f"{struct_type.name}.offsetof: field name must be a str")
        try:
            layout = struct_layout(struct_type, struct_lookup(self.env))
            offset = layout.offset_of(name.value)
        except LayoutError as e:
            raise TypeError(f"{struct_type.name}.offsetof: {e}"
                            if "no field" in str(e) else str(e))
        return UnitValue(mk_int(offset), BUILTIN_UNITS["byte"])

    def _struct_layout_attr(self, struct_type, attr: str):
        """Return a struct's C size or alignment as a byte-valued result.

        Both are only meaningful for a struct whose layout is defined,
        so a struct without @repr(C) reports why the question cannot be
        answered rather than inventing a number.
        """
        from interp.layout import LayoutError, struct_layout, struct_lookup
        from interp.units import BUILTIN_UNITS

        try:
            layout = struct_layout(struct_type, struct_lookup(self.env))
        except LayoutError as e:
            raise TypeError(str(e))
        value = layout.size if attr == "sizeof" else layout.align
        return UnitValue(mk_int(value), BUILTIN_UNITS["byte"])

    def _sizeof_result(self, count: int, element_type: str | None = None):
        from interp.units import BUILTIN_UNITS
        if element_type in ("u8", "byte"):
            return UnitValue(mk_int(count), BUILTIN_UNITS["byte"])
        return UnitValue(mk_int(count), BUILTIN_UNITS["ptrdiff"])

    @staticmethod
    def _check_index_unit(iu: Value, arr: ArrayValue) -> IntValue:
        """Validate that an array index is an integer with a compatible unit.

        Untyped integer constants (width "int") are always accepted.
        Unit-bearing indices must match the array kind: byte for
        u8[]/byte[], ptrdiff for everything else.  Typed integers
        without a unit (e.g. i32, u64) are rejected — they must
        carry the correct unit annotation.
        """
        from interp.units import BUILTIN_UNITS
        is_byte_array = arr.element_type in ("u8", "byte")
        required = BUILTIN_UNITS["byte"] if is_byte_array else BUILTIN_UNITS["ptrdiff"]
        if isinstance(iu, UnitValue):
            if not iu.unit.same_dimension(required):
                raise TypeError(
                    f"array index requires unit {required.display_name}, "
                    f"got {iu.unit.display_name}")
            if not isinstance(iu.inner, IntValue):
                raise TypeError("array index must be an integer")
            return iu.inner
        if isinstance(iu, IntValue):
            if iu.width == "int":
                return iu
            raise TypeError(
                f"array index requires unit {required.display_name}, "
                f"got typed integer {iu.width} without unit")
        raise TypeError("array index must be an integer")

    def _alloc_nested(self, sizes: list[int], fill: Value,
                      etype: str | None) -> Value:
        """Build an array of the given dimensions filled with one value.

        The innermost dimension holds the fill; each dimension above it
        holds that many of whatever the level below built.
        """
        inner = sizes[1:]
        if not inner:
            return ObjectValue(ArrayValue([fill] * sizes[0],
                                          element_type=etype,
                                          fixed_size=sizes[0]))
        rows = [self._alloc_nested(inner, fill, etype) for _ in range(sizes[0])]
        return ObjectValue(ArrayValue(rows, fixed_size=sizes[0]))

    def _eval_multi_slice_read(self, val: Value, specs: list) -> Value:
        """Read a multi-dimensional slice from a nested array."""
        unwrapped = unwrap_optional(val)
        if not isinstance(unwrapped, ObjectValue) or not isinstance(unwrapped.obj, ArrayValue):
            raise TypeError("multi-dimensional slice requires a nested array")
        arr = unwrapped.obj
        kind, *rest = specs[0]
        remaining = specs[1:]
        if kind == "range":
            s_raw = unwrap_optional(self.eval_expr(rest[0]))
            e_raw = unwrap_optional(self.eval_expr(rest[1]))
            s = self._check_index_unit(s_raw, arr)
            e = self._check_index_unit(e_raw, arr)
            selected = [arr.get(i) for i in range(s.value, e.value + 1)]
        else:
            idx_raw = unwrap_optional(self.eval_expr(rest[0]))
            idx = self._check_index_unit(idx_raw, arr)
            if remaining:
                return self._eval_multi_slice_read(arr.get(idx.value), remaining)
            return arr.get(idx.value)
        if remaining:
            result = [self._eval_multi_slice_read(elem, remaining) for elem in selected]
            return ObjectValue(ArrayValue(result))
        return ObjectValue(ArrayValue(selected, element_type=arr.element_type))

    def _eval_multi_slice_write(self, val: Value, specs: list, rhs: Value) -> None:
        """Write to a multi-dimensional slice of a nested array."""
        unwrapped = unwrap_optional(val)
        if not isinstance(unwrapped, ObjectValue) or not isinstance(unwrapped.obj, ArrayValue):
            raise TypeError("multi-dimensional slice requires a nested array")
        arr = unwrapped.obj
        kind, *rest = specs[0]
        remaining = specs[1:]
        if kind == "range":
            s_raw = unwrap_optional(self.eval_expr(rest[0]))
            e_raw = unwrap_optional(self.eval_expr(rest[1]))
            s = self._check_index_unit(s_raw, arr)
            e = self._check_index_unit(e_raw, arr)
            rhs_u = unwrap_optional(rhs)
            if not isinstance(rhs_u, ObjectValue) or not isinstance(rhs_u.obj, ArrayValue):
                raise TypeError("slice assignment requires an array on the right-hand side")
            rhs_arr = rhs_u.obj
            for i_out, i_arr in enumerate(range(s.value, e.value + 1)):
                rhs_elem = rhs_arr.get(i_out)
                if remaining:
                    self._eval_multi_slice_write(arr.get(i_arr), remaining, rhs_elem)
                else:
                    arr.set(i_arr, rhs_elem)
        else:
            idx_raw = unwrap_optional(self.eval_expr(rest[0]))
            idx = self._check_index_unit(idx_raw, arr)
            if remaining:
                self._eval_multi_slice_write(arr.get(idx.value), remaining, rhs)
            else:
                arr.set(idx.value, rhs)

    # ------------------------------------------------------------------
    # Expression evaluation
    # ------------------------------------------------------------------

    def eval_expr(self, node):
        """Evaluate an expression AST node and return its runtime Value.

        Args:
            node: an AST node (IntLit, BinOp, FuncCall, etc.).

        Returns:
            A Value instance.
        """
        pos = getattr(node, "pos", None)
        if pos is not None:
            self._last_pos = pos
            if self._call_stack:
                self._call_stack[-1][1] = pos

        if isinstance(node, IntLit):
            return mk_int(node.value, node.width)

        if isinstance(node, FloatLit):
            return mk_float(node.value, node.width)

        if isinstance(node, StrLit):
            return mk_str(node.text)

        if isinstance(node, BoolLit):
            return mk_bool(node.value)

        if isinstance(node, NoneLit):
            return none()

        if isinstance(node, VarRef):
            if node.name == DISCARD_NAME:
                raise TypeError(
                    "'_' discards the value assigned to it and cannot be read")
            if self._frozen_vars.get(node.name) == "moved":
                raise TypeError(
                    f"use of moved value '{node.name}'")
            if (self._pure_func_name is not None
                    and not self.env.has_local(node.name)
                    and self.env.is_mutable_global(node.name)):
                raise TypeError(
                    f"pure function '{self._pure_func_name}' cannot "
                    f"read mutable global variable '{node.name}'")
            try:
                val = self.env.lookup(node.name)
            except KeyError:
                # A type name stands for its type wherever it appears,
                # which is what lets @typeof be compared against it.
                if is_type_name(node.name):
                    return TypeValue(node.name)
                raise
            if isinstance(val, Reference):
                return val.get()
            return val

        if isinstance(node, RefExpr):
            self.env.lookup(node.name)
            return RefValue(self.env, node.name)

        if isinstance(node, StaticAssert):
            for arg in node.args:
                if not _is_const_expr(arg):
                    raise TypeError(
                        "static_assert requires compile-time constant expressions")
            if not node.args:
                raise TypeError("static_assert requires at least 1 argument")
            cond = self.eval_expr(node.args[0])
            if isinstance(cond, BoolValue):
                if not cond.value:
                    msg = ""
                    if len(node.args) > 1:
                        m = self.eval_expr(node.args[1])
                        msg = f": {m.display()}" if hasattr(m, "display") else ""
                    raise TypeError(f"static_assert failed{msg}")
            elif isinstance(cond, IntValue):
                if cond.value == 0:
                    raise TypeError("static_assert failed: value is zero")
            else:
                raise TypeError("static_assert condition must be bool or int")
            return none()

        if isinstance(node, StaticAssertEq):
            if not _is_const_expr(node.expected) or not _is_const_expr(node.actual):
                raise TypeError(
                    "static_assert_eq requires compile-time constant expressions")
            expected = self.eval_expr(node.expected)
            actual = self.eval_expr(node.actual)
            eu = _as_type_value(unwrap_optional(expected))
            au = _as_type_value(unwrap_optional(actual))
            if isinstance(eu, IntValue) and isinstance(au, IntValue):
                if eu.value != au.value:
                    raise TypeError(
                        f"static_assert_eq failed:\n  expected: {eu.display()}\n  actual:   {au.display()}")
            elif isinstance(eu, StrValue) and isinstance(au, StrValue):
                if eu.value != au.value:
                    raise TypeError(
                        f"static_assert_eq failed:\n  expected: {eu.display()}\n  actual:   {au.display()}")
            elif isinstance(eu, BoolValue) and isinstance(au, BoolValue):
                if eu.value != au.value:
                    raise TypeError(
                        f"static_assert_eq failed:\n  expected: {eu.display()}\n  actual:   {au.display()}")
            elif isinstance(eu, TypeValue) and isinstance(au, TypeValue):
                if eu.name != au.name:
                    raise TypeError(
                        f"static_assert_eq failed:\n  expected: {eu.display()}\n  actual:   {au.display()}")
            elif (isinstance(eu, TypeValue) and isinstance(au, StrValue)) or \
                 (isinstance(eu, StrValue) and isinstance(au, TypeValue)):
                # A type may also be checked against its name as a
                # string, which predates naming the type directly.
                type_name = eu.name if isinstance(eu, TypeValue) else au.name
                spelled = au.value if isinstance(au, StrValue) else eu.value
                if type_name != spelled:
                    raise TypeError(
                        f"static_assert_eq failed:\n  expected: {type_name}\n"
                        f"  actual:   {spelled}")
            elif isinstance(eu, UnitValue) and isinstance(au, UnitValue):
                # Through the arithmetic's own comparison, so that the
                # units have to agree as well as the numbers.
                eq = self._unit_binop("==", eu, au)
                if not eq.value:
                    raise TypeError(
                        f"static_assert_eq failed:\n  expected: {eu.display()}\n  actual:   {au.display()}")
            elif isinstance(eu, UnitOfValue) and isinstance(au, UnitOfValue):
                eq = self._op_eq(expected, actual)
                if not eq.value:
                    raise TypeError(
                        f"static_assert_eq failed:\n  expected: {eu.display()}\n  actual:   {au.display()}")
            else:
                raise TypeError(
                    f"static_assert_eq failed:\n  expected: {eu.display()}\n  actual:   {au.display()}")
            return none()

        if isinstance(node, WrapExpr):
            old = self._wrapping
            self._wrapping = True
            try:
                return self.eval_expr(node.expr)
            finally:
                self._wrapping = old

        if isinstance(node, BinOp):
            binop_pos = pos
            if node.op == "??":
                left = self.eval_expr(node.left)
                if isinstance(left, ExpectedValue):
                    if left.is_ok():
                        return left.ok_value
                    return self.eval_expr(node.right)
                if isinstance(left, SomeValue):
                    return left.value
                if isinstance(left, NoneValue):
                    return self.eval_expr(node.right)
                return left
            left = self.eval_expr(node.left)
            right = self.eval_expr(node.right)
            if binop_pos is not None:
                self._last_pos = binop_pos
                if self._call_stack:
                    self._call_stack[-1][1] = binop_pos
            if node.op == "\N{DOUBLE PLUS}":
                return self._op_concat(left, right)
            lu = unwrap_optional(left)
            ru = unwrap_optional(right)
            if isinstance(lu, UnitValue) or isinstance(ru, UnitValue):
                return self._unit_binop(node.op, lu, ru)
            return self._apply_binop(self._ops[node.op], left, right)

        if isinstance(node, UnitExpr):
            value = self.eval_expr(node.expr)
            from interp.units import eval_unit_formula
            unit = eval_unit_formula(node.unit_spec)
            if isinstance(value, UnitValue):
                return UnitValue(value.inner, unit)
            return UnitValue(value, unit)

        if isinstance(node, UnaryOp):
            operand = self.eval_expr(node.operand)
            if node.op == "⁻":
                unwrapped = unwrap_optional(operand)
                if isinstance(unwrapped, UnitValue):
                    inner = unwrapped.inner
                    if isinstance(inner, IntValue):
                        return UnitValue(self._mk_int(-inner.value, inner.width), unwrapped.unit)
                    if isinstance(inner, FloatValue):
                        return UnitValue(mk_float(-inner.value, inner.width), unwrapped.unit)
                if isinstance(unwrapped, IntValue):
                    return self._mk_int(-unwrapped.value, unwrapped.width)
                if isinstance(unwrapped, FloatValue):
                    return mk_float(-unwrapped.value, unwrapped.width)
                raise TypeError(f"negation expected numeric type, got {type(unwrapped).__name__}")
            if node.op == "~":
                unwrapped = unwrap_optional(operand)
                if isinstance(unwrapped, UnitValue):
                    inner = unwrapped.inner
                    if isinstance(inner, IntValue):
                        return UnitValue(mk_int_wrap(~inner.value, inner.width), unwrapped.unit)
                    raise TypeError(f"bitwise-not expected int, got {type(inner).__name__}")
                if isinstance(unwrapped, EnumValue):
                    if not unwrapped.enum_type.is_flag:
                        raise TypeError(
                            f"bitwise-not requires @flag enum, got '{unwrapped.enum_type.name}'")
                    all_bits = 0
                    for v in unwrapped.enum_type.members.values():
                        all_bits |= v
                    return EnumValue(unwrapped.enum_type, ~unwrapped.value & all_bits)
                if isinstance(unwrapped, IntValue):
                    return mk_int_wrap(~unwrapped.value, unwrapped.width)
                raise TypeError(f"bitwise-not expected int, got {type(unwrapped).__name__}")
            if node.op == "¬":
                unwrapped = unwrap_optional(operand)
                return mk_bool(not self._logic_bool(unwrapped))
            if node.op == "not":
                return mk_bool(not to_bool(operand))
            if node.op in ("\N{SQUARE ROOT}", "\N{CUBE ROOT}", "\N{FOURTH ROOT}"):
                import math
                degree = {"\N{SQUARE ROOT}": 2, "\N{CUBE ROOT}": 3, "\N{FOURTH ROOT}": 4}[node.op]
                unwrapped = unwrap_optional(operand)
                if isinstance(unwrapped, UnitValue):
                    inner = unwrapped.inner
                    if not isinstance(inner, FloatValue):
                        raise TypeError(
                            f"{node.op} requires floating-point operand, "
                            f"got {type(inner).__name__}")
                    result_val = inner.value ** (1.0 / degree)
                    result_float = mk_float(result_val, inner.width)
                    unit = unwrapped.unit
                    for k, v in unit.components.items():
                        if v != 0 and v % degree != 0:
                            raise TypeError(
                                f"cannot take {node.op} of unit "
                                f"{unit.display_name}: dimension '{k}' "
                                f"has exponent {v} not divisible by {degree}")
                    from fractions import Fraction
                    from interp.units import Unit
                    new_components = {k: v // degree
                                     for k, v in unit.components.items()}
                    num_root = _nth_root_exact(unit.factor.numerator, degree)
                    den_root = _nth_root_exact(unit.factor.denominator, degree)
                    if num_root is None or den_root is None:
                        raise TypeError(
                            f"cannot take {node.op} of unit "
                            f"{unit.display_name}: factor {unit.factor} "
                            f"is not a perfect {degree}-th power")
                    new_factor = Fraction(num_root, den_root)
                    from interp.units import _display_from_components
                    new_unit = Unit(
                        new_components, new_factor,
                        _display_from_components(
                            {k: v for k, v in new_components.items()
                             if v != 0}))
                    if new_unit.is_dimensionless():
                        return result_float
                    return UnitValue(result_float, new_unit)
                if isinstance(unwrapped, FloatValue):
                    result_val = unwrapped.value ** (1.0 / degree)
                    return mk_float(result_val, unwrapped.width)
                raise TypeError(
                    f"{node.op} requires floating-point operand, "
                    f"got {type(unwrapped).__name__}")

        if isinstance(node, OptSome):
            value = self.eval_expr(node.value)
            return some(value)

        if isinstance(node, ExpErr):
            return ExpectedValue.err(self.eval_expr(node.value))

        if isinstance(node, TryUnwrap):
            if not self._current_ret_type:
                raise TypeError(
                    "? operator requires enclosing function to have optional or expected return type")
            _, opt_err = _split_optional_type(self._current_ret_type)
            if opt_err is None:
                raise TypeError(
                    "? operator requires enclosing function to have optional or expected return type")
            val = self.eval_expr(node.expr)
            if isinstance(val, ExpectedValue):
                if val.is_ok():
                    return val.ok_value
                if opt_err != "":
                    # The static check catches this wherever the error
                    # type can be worked out from the source; this is
                    # the backstop for the cases where it cannot.
                    actual = self._value_type_name(val.err_value)
                    if actual != opt_err.rsplit(".", 1)[-1]:
                        raise TypeError(
                            f"? propagates an error of type '{actual}', but "
                            f"the function returns errors of type "
                            f"'{opt_err}'")
                    raise _ReturnSentinel(ExpectedValue.err(val.err_value))
                raise _ReturnSentinel(none())
            if isinstance(val, SomeValue):
                return val.value
            if isinstance(val, NoneValue):
                raise _ReturnSentinel(none())
            return val

        if isinstance(node, StructLit):
            return self._eval_struct_lit(node)

        if isinstance(node, FuncCall):
            args = [self.eval_expr(a) for a in node.args]
            return self._call_func(node.name, args)

        if isinstance(node, MethodCall):
            if node.method in _ARRAY_MUTATORS:
                self._check_mutating_call(node)
            obj = self.eval_expr(node.obj)
            args = [self.eval_expr(a) for a in node.args]
            result = self._call_method(obj, node.method, args)
            unwrapped_obj = unwrap_optional(obj)
            if (isinstance(unwrapped_obj, ObjectValue)
                    and isinstance(unwrapped_obj.obj, StructInstance)
                    and isinstance(node.obj, VarRef)):
                inst = unwrapped_obj.obj
                method = inst.struct_type.methods.get(node.method)
                if (method is not None
                        and method.params
                        and method.params[0][0] == "self"
                        and node.method not in inst.struct_type._ref_self_methods):
                    self._frozen_vars[node.obj.name] = "moved"
            return result

        if isinstance(node, GetAttr):
            obj = self.eval_expr(node.obj)
            unwrapped = unwrap_optional(obj)
            if isinstance(unwrapped, EnumType):
                if node.attr in unwrapped.members:
                    return EnumValue(unwrapped, unwrapped.members[node.attr])
                raise AttributeError(
                    f"enum '{unwrapped.name}' has no member '{node.attr}'")
            if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, StructInstance):
                inst = unwrapped.obj
                if node.attr in inst.field_values:
                    return inst.field_values[node.attr]
                if node.attr in ("sizeof", "alignof"):
                    return self._struct_layout_attr(inst.struct_type, node.attr)
                raise AttributeError(
                    f"struct '{inst.struct_type.name}' has no field '{node.attr}'")
            if isinstance(unwrapped, StructType):
                if node.attr in ("sizeof", "alignof"):
                    return self._struct_layout_attr(unwrapped, node.attr)
                raise AttributeError(
                    f"struct type '{unwrapped.name}' has no attribute "
                    f"'{node.attr}'")
            if isinstance(unwrapped, TupleValue):
                if node.attr == "sizeof":
                    return self._sizeof_result(len(unwrapped.elements))
            if isinstance(unwrapped, StrValue):
                if node.attr == "sizeof":
                    return self._sizeof_result(len(unwrapped.value))
            if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
                if node.attr == "sizeof":
                    return self._sizeof_result(
                        unwrapped.obj.sizeof,
                        unwrapped.obj.element_type)
                if node.attr == "shape":
                    # One extent per dimension, which is how a function
                    # reads the dimensions its parameter type left open.
                    return TupleValue([
                        self._sizeof_result(d) if d is not None else none()
                        for d in array_shape(unwrapped.obj)])
            if isinstance(unwrapped, ObjectValue):
                attr_val = getattr(unwrapped.obj, node.attr, None)
                if attr_val is not None:
                    if isinstance(attr_val, Value):
                        return attr_val
                    if callable(attr_val):
                        return BuiltinBoundMethod(unwrapped.obj, node.attr)
                    # bool before int: bool is a subclass of int, so the
                    # int test would otherwise turn true/false into 1/0.
                    if isinstance(attr_val, bool):
                        return mk_bool(attr_val)
                    if isinstance(attr_val, int):
                        return mk_int(attr_val)
                    if isinstance(attr_val, str):
                        return mk_str(attr_val)
                    return ObjectValue(attr_val)
            elif isinstance(unwrapped, IntValue):
                # int.value attribute? No, just return the int itself.
                pass
            return obj

        # Array literal [expr, expr, ...].
        if isinstance(node, ArrayLit):
            elements = [self.eval_expr(e) for e in node.elements]
            return ObjectValue(ArrayValue(elements))

        # Subscript read: arr[i] or arr[i, j, ...] or tuple[i].
        if isinstance(node, Subscript):
            val = self.eval_expr(node.obj)
            for idx_node in node.indices:
                unwrapped = unwrap_optional(val)
                idx_val = self.eval_expr(idx_node)
                iu = unwrap_optional(idx_val)
                if isinstance(unwrapped, TupleValue):
                    if isinstance(iu, UnitValue):
                        iu = iu.inner
                    if isinstance(iu, IntValue):
                        val = unwrapped.get(iu.value)
                    else:
                        raise TypeError("tuple index must be an integer")
                elif isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
                    iu = self._check_index_unit(iu, unwrapped.obj)
                    val = unwrapped.obj.get(iu.value)
                else:
                    raise TypeError("multi-dimensional subscript requires nested arrays or tuples")
            return val

        # Slice read: arr[start…end] (inclusive).
        if isinstance(node, SliceAccess):
            arr_val = self.eval_expr(node.obj)
            unwrapped = unwrap_optional(arr_val)
            if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
                s = unwrap_optional(self.eval_expr(node.start))
                e = unwrap_optional(self.eval_expr(node.end))
                s = self._check_index_unit(s, unwrapped.obj)
                e = self._check_index_unit(e, unwrapped.obj)
                arr = unwrapped.obj
                elems = [arr.get(i) for i in range(s.value, e.value + 1)]
                return ObjectValue(ArrayValue(list(elems),
                                              element_type=arr.element_type))

        # Multi-dimensional slice: arr[range, range, ...].
        if isinstance(node, MultiSlice):
            arr_val = self.eval_expr(node.obj)
            return self._eval_multi_slice_read(arr_val, node.specs)

        if isinstance(node, RangeExpr):
            s = unwrap_optional(self.eval_expr(node.start))
            e = unwrap_optional(self.eval_expr(node.end))
            if isinstance(s, UnitValue):
                s = s.inner
            if isinstance(e, UnitValue):
                e = e.inner
            if not isinstance(s, IntValue) or not isinstance(e, IntValue):
                raise TypeError("range bounds must be integers")
            step = None
            if node.step is not None:
                st = unwrap_optional(self.eval_expr(node.step))
                if isinstance(st, UnitValue):
                    st = st.inner
                if not isinstance(st, IntValue):
                    raise TypeError("range step must be an integer")
                step = st.value
            return RangeValue(s.value, e.value, step)

        if isinstance(node, EnumerateExpr):
            raise TypeError("enumerate can only be used inside foreach")

        if isinstance(node, TypeOfExpr):
            cached = getattr(node, "_cached_value", None)
            if cached is not None:
                return cached
            if not _is_comptime_expr(node.expr, self._comptime_vars) \
                    and not self._names_a_binding(node.expr):
                raise TypeError(
                    "@typeof requires a compile-time constant, a name, or "
                    "an expression built from them")
            # Reading a name bound to a reference yields the referent, so
            # the binding itself is inspected to report the borrow.
            val = None
            if isinstance(node.expr, VarRef):
                try:
                    bound = self.env.lookup(node.expr.name)
                except KeyError:
                    bound = None
                if isinstance(bound, Reference):
                    val = bound
            if val is None:
                val = self.eval_expr(node.expr)
            result = TypeValue(self._value_type_name(val))
            if _is_const_expr(node.expr):
                node._cached_value = result
            return result

        if isinstance(node, DropUnitExpr):
            val = self.eval_expr(node.expr)
            inner = val.inner if isinstance(val, UnitValue) else val
            if not isinstance(val, UnitValue):
                self._warnings.append(
                    "@dropunit: this value carries no unit to drop")
            return inner

        if isinstance(node, SizeOfExpr):
            cached = getattr(node, "_cached_value", None)
            if cached is not None:
                return cached
            # A written type asks how much storage it occupies; a value
            # asks how many elements it holds.
            written = self._written_type(node.expr)
            if written is not None:
                result = self._type_byte_size(written)
                node._cached_value = result
                return result
            named = self._names_a_binding(node.expr)
            if not _is_comptime_expr(node.expr, self._comptime_vars) \
                    and not named:
                raise TypeError(
                    "@sizeof requires a compile-time constant, a name, or "
                    "an expression built from them")
            val = self.eval_expr(node.expr)
            unwrapped = unwrap_optional(val)
            if isinstance(unwrapped, TupleValue):
                result = self._sizeof_result(len(unwrapped.elements))
            elif isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
                # A name answers from its type, and a length is only in
                # the type when the type states it.  A dynamically sized
                # array has a length but not one @sizeof can claim.
                if named and unwrapped.obj.fixed_size is None:
                    raise TypeError(
                        f"@sizeof: {self._describe_operand(node.expr)} is a "
                        f"dynamically sized array, whose length is not part "
                        f"of its type; use .sizeof to read it")
                result = self._sizeof_result(
                    unwrapped.obj.sizeof,
                    unwrapped.obj.element_type)
            elif isinstance(unwrapped, StrValue):
                # A literal's length is written down and is the count it
                # asks for; a name's is the value's, not the type's.
                if isinstance(node.expr, VarRef):
                    raise TypeError(
                        f"@sizeof: '{node.expr.name}' is a string, whose "
                        f"length is not part of its type; use .sizeof to "
                        f"read it")
                result = self._sizeof_result(len(unwrapped.value))
            elif named:
                # A scalar holds no elements to count, but its type
                # says what it occupies, which is the only size it has.
                result = self._type_byte_size(runtime_type_of(unwrapped))
            else:
                raise TypeError(
                    f"@sizeof: expected array, tuple, or string, "
                    f"got {type(unwrapped).__name__}")
            if _is_const_expr(node.expr):
                node._cached_value = result
            return result

        if isinstance(node, ResultOfExpr):
            cached = getattr(node, "_cached_value", None)
            if cached is not None:
                return cached
            try:
                func = self.env.lookup(node.name)
            except KeyError:
                raise TypeError(f"@resultof: unknown function '{node.name}'")
            if isinstance(func, FuncValue):
                result = TypeValue(func.ret_type or "\N{EMPTY SET}")
            elif isinstance(func, BuiltinFunc):
                result = TypeValue("builtin")
            else:
                raise TypeError(f"@resultof: '{node.name}' is not a function")
            node._cached_value = result
            return result

        if isinstance(node, UnitOfExpr):
            cached = getattr(node, "_cached_value", None)
            if cached is not None:
                return cached
            if not _is_comptime_expr(node.expr, self._comptime_vars) \
                    and not self._names_a_binding(node.expr):
                raise TypeError(
                    "@unitof requires a compile-time constant, a name, or "
                    "an expression built from them")
            val = self.eval_expr(node.expr)
            unwrapped = unwrap_optional(val)
            if isinstance(unwrapped, UnitValue):
                result = UnitOfValue(unwrapped.unit)
            else:
                result = UnitOfValue(None)
            if _is_const_expr(node.expr):
                node._cached_value = result
            return result

        if isinstance(node, UnitRefExpr):
            from interp.units import eval_unit_formula
            unit = eval_unit_formula(node.unit_spec)
            return UnitOfValue(unit)

        if isinstance(node, LambdaExpr):
            return self._eval_lambda_expr(node)

        if isinstance(node, TupleLit):
            elements = [self.eval_expr(e) for e in node.elements]
            return TupleValue(elements)

        if isinstance(node, FoldExpr):
            return self._eval_fold(node)

        if isinstance(node, ReshapeExpr):
            shape = self.eval_expr(node.shape)
            data = self.eval_expr(node.data)
            return self._eval_reshape(shape, data)

        # Array allocation: new type[size] or var name : type[size] = init.
        if isinstance(node, ArrayAlloc):
            etype = node.element_type
            if etype and etype in FAST_TYPES:
                raise TypeError(
                    f"fast type '{etype}' cannot be used as array element type")
            sizes = []
            for dim in [node.size_expr, *node.rest_dims]:
                if dim is None:
                    # Left empty, so the initializer decides it.
                    sizes.append(None)
                    continue
                dv = unwrap_optional(self.eval_expr(dim))
                if isinstance(dv, UnitValue):
                    dv = dv.inner
                if not isinstance(dv, IntValue):
                    sizes = None
                    break
                sizes.append(dv.value)
            if sizes is not None:
                init_val = self.eval_expr(node.init_expr) if node.init_expr is not None else mk_int(0)
                if isinstance(init_val, ObjectValue) and isinstance(init_val.obj, ArrayValue):
                    declared = format_shape(sizes)
                    actual = array_shape(init_val.obj)
                    if len(actual) != len(sizes) or any(
                            have is None or (want is not None and want != have)
                            for want, have in zip(sizes, actual)):
                        raise TypeError(
                            f"array size mismatch: declared {declared}, "
                            f"got {format_shape(actual)}")
                    # An empty extent takes the one the initializer had.
                    sizes = list(actual)
                    # The declared length travels with the value, so the
                    # operations that would change it can refuse.
                    arr = init_val.obj
                    elements = [arr.get(i) for i in range(arr.sizeof)]
                    if etype and len(sizes) == 1:
                        elements = [coerce_to_type(e, etype) for e in elements]
                    return ObjectValue(ArrayValue(elements, element_type=etype,
                                                  fixed_size=sizes[0]))
                if any(d is None for d in sizes):
                    raise TypeError(
                        f"array size mismatch: declared {format_shape(sizes)}, "
                        f"but a fill value gives no extent for the empty "
                        f"dimension")
                if etype:
                    # Through coerce_to_type rather than mk_int, which
                    # would take any element type for an integer width
                    # and build a value whose width is a type name.
                    init_val = coerce_to_type(init_val, etype)
                return self._alloc_nested(sizes, init_val, etype)

        raise TypeError(f"unexpected expression: {type(node).__name__}")

    # ------------------------------------------------------------------
    # Statement evaluation
    # ------------------------------------------------------------------

    def eval_stmts(self, stmts):
        """Evaluate a list of statements in order.

        Args:
            stmts: list of statement AST nodes.

        Returns:
            The result Value of the last executed expression/return, or NoneValue.

        Raises:
            _ReturnSentinel: when a return statement is encountered (caught by caller).
        """
        result = none()
        for stmt in stmts:
            result = self.eval_stmt(stmt)
            if isinstance(result, _ReturnSentinel):
                raise result
        return result

    def eval_stmt(self, stmt):
        """Evaluate a single statement, releasing what it does not keep.

        Resources produced while the statement runs but neither bound to
        a name nor handed back as its value are released as it finishes.

        Returns:
            The last computed value, or a _ReturnSentinel for return statements.
        """
        outer = self._temporaries
        self._temporaries = []
        try:
            result = self._eval_stmt(stmt)
            self._release_temporaries(result)
            return result
        except BaseException:
            self._release_temporaries(None)
            raise
        finally:
            self._temporaries = outer

    def _eval_stmt(self, stmt):
        """Evaluate a single statement.

        Returns:
            The last computed value, or a _ReturnSentinel for return statements.
        """
        pos = getattr(stmt, "pos", None)
        if pos is not None:
            self._last_pos = pos
            if self._call_stack:
                self._call_stack[-1][1] = pos

        if isinstance(stmt, ExpectStmt):
            return self._eval_expect(stmt)

        # Handle assignment tuple returned by parser: ("assign", name, rhs_ast).
        if isinstance(stmt, tuple) and len(stmt) == 3 and stmt[0] == "assign":
            _, name, rhs_ast = stmt
            value = self.eval_expr(rhs_ast)
            self.env.define(name, value)
            return none()

        # Handle const definition: ("const_assign", name, type_ann, init_expr).
        if isinstance(stmt, tuple) and len(stmt) == 4 and stmt[0] == "const_assign":
            _, name, type_ann, init_expr = stmt
            value = self.eval_expr(init_expr)
            if type_ann is not None:
                value = coerce_to_type(value, type_ann)
            self.env.define(name, value)
            return none()

        # Handle generalized assignment: ("assign_stmt", lhs_expr_ast, rhs_ast).
        # LHS can be a VarRef (variable shadowing) or Subscript (array mutation).
        if isinstance(stmt, tuple) and len(stmt) == 3 and stmt[0] == "assign_stmt":
            _, target_ast, rhs_ast = stmt
            target_pos = getattr(target_ast, "pos", None)
            if target_pos is not None:
                self._last_pos = target_pos
            self._check_assignable(target_ast)
            rhs = self.eval_expr(rhs_ast)
            if isinstance(target_ast, VarRef):
                self._check_assigned_kind(target_ast.name, rhs)
            if isinstance(target_ast, MultiSlice):
                # arr[range, range, ...] ← matrix — multi-dim slice write.
                arr_val = self.eval_expr(target_ast.obj)
                self._eval_multi_slice_write(arr_val, target_ast.specs, rhs)
            elif isinstance(target_ast, SliceAccess):
                # arr[s…e] ← rhs_array — copy elements into slice.
                arr_val = self.eval_expr(target_ast.obj)
                au = unwrap_optional(arr_val)
                if isinstance(au, ObjectValue) and isinstance(au.obj, ArrayValue):
                    s = unwrap_optional(self.eval_expr(target_ast.start))
                    e = unwrap_optional(self.eval_expr(target_ast.end))
                    s = self._check_index_unit(s, au.obj)
                    e = self._check_index_unit(e, au.obj)
                    rhs_arr = self._as_array(rhs)
                    if rhs_arr is not None:
                        for i in range(rhs_arr.sizeof):
                            au.obj.set(s.value + i, rhs_arr.get(i))
            elif isinstance(target_ast, Subscript):
                # arr[i] or arr[i, j, ...] ← value — mutate (nested) array element.
                val = self.eval_expr(target_ast.obj)
                for idx_node in target_ast.indices[:-1]:
                    unwrapped = unwrap_optional(val)
                    idx_val = self.eval_expr(idx_node)
                    iu = unwrap_optional(idx_val)
                    if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
                        iu = self._check_index_unit(iu, unwrapped.obj)
                        val = unwrapped.obj.get(iu.value)
                    else:
                        raise TypeError("multi-dimensional subscript requires nested arrays")
                last_idx_node = target_ast.indices[-1]
                unwrapped = unwrap_optional(val)
                if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
                    idx_val = self.eval_expr(last_idx_node)
                    iu = unwrap_optional(idx_val)
                    iu = self._check_index_unit(iu, unwrapped.obj)
                    unwrapped.obj.set(iu.value, rhs)
            elif isinstance(target_ast, GetAttr):
                obj_val = self.eval_expr(target_ast.obj)
                au = unwrap_optional(obj_val)
                if isinstance(au, ObjectValue) and isinstance(au.obj, StructInstance):
                    inst = au.obj
                    if target_ast.attr not in inst.field_values:
                        raise TypeError(
                            f"struct '{inst.struct_type.name}' has no field "
                            f"'{target_ast.attr}'")
                    field_type = None
                    for fname, ftype in inst.struct_type.fields:
                        if fname == target_ast.attr:
                            field_type = ftype
                            break
                    if field_type is not None:
                        rhs = coerce_arg(rhs, field_type, "field assignment",
                                         target_ast.attr)
                    inst.field_values[target_ast.attr] = rhs
                else:
                    raise TypeError("field assignment requires a struct instance")
            elif isinstance(target_ast, VarRef):
                if target_ast.name == DISCARD_NAME:
                    # The right-hand side has already been evaluated for
                    # its effects; the result is simply dropped.  No type
                    # check applies, since there is nothing to store into.
                    return none()
                if target_ast.name in self._frozen_vars:
                    kind = self._frozen_vars[target_ast.name]
                    if kind == "moved":
                        del self._frozen_vars[target_ast.name]
                    else:
                        raise TypeError(
                            f"cannot assign to {kind} variable "
                            f"'{target_ast.name}'")
                if self.env.is_const_global(target_ast.name):
                    raise TypeError(
                        f"cannot assign to let variable "
                        f"'{target_ast.name}'")
                if (self._pure_func_name is not None
                        and not self.env.has_local(target_ast.name)):
                    raise TypeError(
                        f"pure function '{self._pure_func_name}' cannot "
                        f"assign to non-local variable '{target_ast.name}'")
                current = self.env.lookup(target_ast.name)
                if isinstance(current, Reference):
                    current.set(rhs)
                    return none()
                if isinstance(current, UnitValue):
                    if isinstance(rhs, UnitValue):
                        rhs = self._convert_unit_value(rhs, current.unit)
                    else:
                        raise TypeError(
                            f"cannot assign dimensionless value to "
                            f"'{target_ast.name}' which has unit "
                            f"{current.unit.display_name}")
                if not self.env.has_local(target_ast.name):
                    self.env.assign(target_ast.name, rhs)
                else:
                    self.env.define(target_ast.name, rhs)
            return none()

        if isinstance(stmt, VarDef):
            if stmt.type_annotation is not None:
                check_bootstrap_type(stmt.type_annotation,
                                     f"'{stmt.name}'")
            if is_type_name(stmt.name):
                raise TypeError(
                    f"'{stmt.name}' names a type and cannot name a variable")
            if stmt.name == DISCARD_NAME:
                # `let _ := expr` discards too, so that a value can be
                # thrown away without inventing a name for it.
                self.eval_expr(stmt.init_expr)
                return none()
            if stmt.name in self._frozen_vars:
                kind = self._frozen_vars[stmt.name]
                if kind == "foreach":
                    self._warnings.append(
                        f"redefinition of foreach variable '{stmt.name}'")
                elif not stmt.is_const:
                    raise TypeError(
                        f"cannot redefine {kind} variable '{stmt.name}'")
            value = self.eval_expr(stmt.init_expr)
            if stmt.type_annotation is not None:
                ann = stmt.type_annotation
                if self._generic_map and is_generic_type(ann):
                    ann = _substitute_generics(ann, self._generic_map)
                value = coerce_to_type(value, ann)
            if stmt.unit_spec is not None:
                from interp.units import eval_unit_formula
                unit = eval_unit_formula(stmt.unit_spec)
                if isinstance(value, UnitValue):
                    value = self._convert_unit_value(value, unit)
                else:
                    value = UnitValue(value, unit)
            self.env.define(stmt.name, value)
            if not self._bind_reshape_access(stmt):
                if stmt.is_const:
                    self._frozen_vars[stmt.name] = "let"
            return none()

        if isinstance(stmt, SumTypeDef):
            register_sum_type(stmt.name, stmt.alternatives)
            return none()

        if isinstance(stmt, TypeDef):
            target = stmt.target
            if self._generic_map and is_generic_type(target):
                target = _substitute_generics(target, self._generic_map)
            register_type_alias(stmt.name, target)
            return none()

        if isinstance(stmt, ExprStmt):
            result = self.eval_expr(stmt.expr)
            if isinstance(result, LambdaValue):
                self._warnings.append(
                    "lambda value is not used (not assigned or returned)")
            return result

        if isinstance(stmt, IfStmt):
            return self._eval_if(stmt)

        if isinstance(stmt, WhileStmt):
            return self._eval_while(stmt)

        if isinstance(stmt, ForEachStmt):
            return self._eval_foreach(stmt)

        if isinstance(stmt, MatchStmt):
            return self._eval_match(stmt)

        if isinstance(stmt, CatchStmt):
            return self._eval_catch(stmt)

        if isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                value = self.eval_expr(stmt.value)
            else:
                value = none()
            raise _ReturnSentinel(value)

        return none()

    def _eval_if(self, node: IfStmt):
        """Evaluate an if/elif/else statement."""
        cond = to_bool(self.eval_expr(node.cond))
        if cond:
            self.eval_stmts(node.cons)
            return none()
        alt = node.alt
        while alt is not None:
            alt_cond, alt_body, *rest = alt
            if alt_cond is None or to_bool(self.eval_expr(alt_cond)):
                self.eval_stmts(alt_body)
                return none()
            alt = rest[0] if rest else None
        return none()

    def _reshape_binding_source(self, stmt):
        """Describe the source a reshape binding inherits its access from.

        A binding takes its access from the reshape's source only when
        it declares no type of its own.  Naming a full type is how a
        program says what it wants instead of what it was given, and
        that declaration is then the one that counts.

        Returns (name, frozen_kind) for such a binding, or None.
        """
        if stmt.type_annotation is not None:
            return None
        expr = stmt.init_expr
        if not isinstance(expr, ReshapeExpr):
            return None
        inner = expr.data
        while isinstance(inner, ReshapeExpr):
            inner = inner.data
        if not isinstance(inner, VarRef):
            return None

        name = inner.name
        kind = self._frozen_vars.get(name)
        if kind == "moved":
            raise TypeError(f"use of moved value '{name}'")
        if kind is None and self.env.is_const_global(name):
            kind = "let"
        return name, kind

    def _bind_reshape_access(self, stmt) -> bool:
        """Give a reshape binding the access its source was held under.

        A reshape shares the storage it was built from, so the binding
        can be written exactly when that storage could.  Asking for mut
        on a source that may only be read is refused: a view cannot hand
        out access its source did not have.

        Returns True when the binding's access was decided here.
        """
        source = self._reshape_binding_source(stmt)
        if source is None:
            return False
        name, kind = source
        if kind is not None:
            if not stmt.is_const:
                raise TypeError(
                    f"cannot take a mutable view of {kind} variable '{name}'")
            self._frozen_vars[stmt.name] = "borrowed"
        else:
            # The source may be written, so the view may be too, whether
            # or not the binding repeated mut.
            self._frozen_vars.pop(stmt.name, None)
        return True

    def _check_assigned_kind(self, name: str, rhs: Value):
        """Refuse an assignment that changes what kind of value a name holds.

        A binding's type does not change under assignment, so a string
        cannot take the place of a number, nor a number of a string.
        Widths still convert, as they do at a definition.
        """
        try:
            current = self.env.lookup(name)
        except KeyError:
            return
        if isinstance(current, Reference):
            current = current.get()
        held = runtime_type_of(unwrap_optional(current))
        mismatch = _scalar_kind_mismatch(unwrap_optional(rhs), held)
        if mismatch is not None:
            raise TypeError(f"'{name}' holds {held} and cannot take {mismatch}")

    def _check_assignable(self, target_ast):
        """Reject a write reaching an immutable binding.

        Writing to an element or a field is writing to the thing that
        holds it, so `let` protects what a binding names and not merely
        the name: a binding that cannot be reassigned cannot have its
        parts assigned either.  The whole chain of subscripts, slices,
        and fields is followed down to the binding it starts from.

        The name itself is left to the VarRef case, which reports
        reassignment rather than a write through.
        """
        part = None
        base = target_ast
        while True:
            if isinstance(base, (Subscript, SliceAccess, MultiSlice)):
                part = part or "element"
                base = base.obj
            elif isinstance(base, GetAttr):
                part = part or f"field '{base.attr}'"
                base = base.obj
            else:
                break
        if part is None or not isinstance(base, VarRef):
            return

        name = base.name
        kind = self._frozen_vars.get(name)
        if kind == "moved":
            raise TypeError(f"use of moved value '{name}'")
        if kind is not None:
            raise TypeError(
                f"cannot assign to {part} of {kind} variable '{name}'")
        if self.env.is_const_global(name):
            raise TypeError(
                f"cannot assign to {part} of let variable '{name}'")

    def _eval_while(self, node: WhileStmt):
        """Evaluate a while loop, with or without a bound variable."""
        if node.var_name is None:
            while to_bool(self.eval_expr(node.cond)):
                self.eval_stmts(node.body)
            return none()

        name = node.var_name
        # A plain binding is rebound every iteration, so assigning to it
        # would be overwritten; it is frozen, as a foreach variable is.
        # A mut binding is the exception, and only means anything when
        # what it names can be written through.
        if not node.var_is_mut:
            self._frozen_vars[name] = "while"
        self._comptime_vars = self._comptime_vars | {name}
        try:
            while True:
                value = self.eval_expr(node.cond)
                if not to_bool(value):
                    # Nothing arrived, so there is nothing to bind and
                    # the body does not run.
                    self.env.define(name, none())
                    break
                # The body runs only when a value was there, so the name
                # is bound to the value itself rather than to the
                # optional wrapping it.
                bound = value.value if isinstance(value, SomeValue) else value
                if node.var_is_mut:
                    if not isinstance(bound, Reference):
                        raise TypeError(
                            f"'{name}' is declared mut, but the loop produces "
                            f"values that cannot be written back")
                elif isinstance(bound, Reference):
                    # A plain binding names the value, not the place it
                    # came from, so it holds a copy and its type is the
                    # element's own.
                    bound = bound.get()
                if node.var_type is not None and not isinstance(bound, Reference):
                    bound = coerce_to_type(bound, node.var_type)
                self.env.define(name, bound)
                self.eval_stmts(node.body)
        finally:
            self._frozen_vars.pop(name, None)
            self._comptime_vars = self._comptime_vars - {name}
        return none()

    def _eval_foreach(self, node: ForEachStmt):
        """Evaluate a foreach loop over ranges or containers."""
        sequences: list[list[Value]] = []
        # None for an ordinary iterable, "shared" or "mut" for a borrow.
        borrows: list[str | None] = []
        for expr in node.iterables:
            if isinstance(expr, BorrowExpr):
                borrows.append("mut" if expr.is_mut else "shared")
                sequences.append(self._resolve_borrow(expr))
                continue
            borrows.append(None)
            if isinstance(expr, EnumerateExpr):
                inner = self._resolve_iterable(expr.expr, node.is_comptime)
                sequences.append([
                    TupleValue([mk_int(i), v]) for i, v in enumerate(inner)
                ])
            elif isinstance(expr, RangeExpr):
                s = unwrap_optional(self.eval_expr(expr.start))
                e = unwrap_optional(self.eval_expr(expr.end))
                range_unit = None
                if isinstance(s, UnitValue):
                    range_unit = s.unit
                    s = s.inner
                if isinstance(e, UnitValue):
                    if range_unit is None:
                        range_unit = e.unit
                    e = e.inner
                if not isinstance(s, IntValue) or not isinstance(e, IntValue):
                    raise TypeError("range bounds must be integers")
                sv, ev = s.value, e.value
                mk_val = (lambda i: UnitValue(mk_int(i), range_unit)) if range_unit is not None else mk_int
                if expr.step is not None:
                    st = unwrap_optional(self.eval_expr(expr.step))
                    if isinstance(st, UnitValue):
                        if range_unit is None:
                            range_unit = st.unit
                            mk_val = lambda i: UnitValue(mk_int(i), range_unit)
                        st = st.inner
                    if not isinstance(st, IntValue):
                        raise TypeError("range step must be an integer")
                    stv = st.value
                    if stv == 0:
                        raise TypeError("range step must not be zero")
                    if stv > 0:
                        sequences.append([mk_val(i) for i in range(sv, ev + 1, stv)])
                    else:
                        sequences.append([mk_val(i) for i in range(sv, ev - 1, stv)])
                elif sv <= ev:
                    sequences.append([mk_val(i) for i in range(sv, ev + 1)])
                else:
                    sequences.append([mk_val(i) for i in range(sv, ev - 1, -1)])
            else:
                sequences.append(self._resolve_iterable(expr, node.is_comptime))

        if not sequences:
            return none()

        max_len = max(len(seq) for seq in sequences)
        num_vars = len(node.vars)
        num_iters = len(sequences)

        destructure = num_vars > 1 and num_iters == 1
        if num_vars > 1 and num_vars != num_iters and not destructure:
            raise TypeError(
                f"foreach: {num_vars} variables but {num_iters} iterables "
                f"(must match or use 1 variable)")

        var_names = [v[0] for v in node.vars]
        for var_name in var_names:
            if is_type_name(var_name):
                raise TypeError(
                    f"'{var_name}' names a type and cannot name a "
                    f"loop variable")

        if any(borrows) and (destructure or num_vars != num_iters):
            raise TypeError(
                "foreach over a borrow needs one variable per borrowed "
                "container")

        # A mutably borrowed variable is the one kind of loop variable
        # that may be assigned to, because assigning to it writes into
        # the container rather than rebinding the name.
        freeze_kinds: list[str | None] = []
        for i in range(num_vars):
            borrow = borrows[i] if i < len(borrows) and num_vars == num_iters else None
            if borrow == "mut":
                freeze_kinds.append(None)
            elif borrow == "shared":
                freeze_kinds.append("borrowed")
            else:
                freeze_kinds.append("foreach")

        for name, kind in zip(var_names, freeze_kinds):
            if kind is not None:
                self._frozen_vars[name] = kind
        self._comptime_vars |= set(var_names)
        try:
            for idx in range(max_len):
                if num_vars == 1 and num_iters > 1:
                    elements = [seq[idx % len(seq)] for seq in sequences]
                    self.env.define(var_names[0], TupleValue(elements))
                elif destructure:
                    val = sequences[0][idx % len(sequences[0])]
                    if not isinstance(val, TupleValue) or len(val.elements) != num_vars:
                        raise TypeError(
                            f"foreach destructuring expects {num_vars}-element tuples")
                    for (var_name, var_type), elem in zip(node.vars, val.elements):
                        if var_type is not None:
                            elem = coerce_to_type(elem, var_type)
                        self.env.define(var_name, elem)
                else:
                    for (var_name, var_type), seq in zip(node.vars, sequences):
                        val = seq[idx % len(seq)]
                        # A reference is bound as-is; coercing it would
                        # replace it with a copy of the element.
                        if var_type is not None and not isinstance(val, Reference):
                            val = coerce_to_type(val, var_type)
                        self.env.define(var_name, val)
                self.eval_stmts(node.body)
        finally:
            for name in var_names:
                self._frozen_vars.pop(name, None)
            self._comptime_vars -= set(var_names)
        return none()

    def _resolve_borrow(self, expr: BorrowExpr) -> list[Value]:
        """Resolve a borrowed iterable to the values the loop will bind.

        A mutable borrow yields a reference per element, so that
        assigning to the loop variable writes into the array.  A shared
        borrow yields the elements themselves; the loop variable is
        frozen, so the copy can never be written back.
        """
        if expr.is_mut and isinstance(expr.expr, VarRef):
            # Writing through a mutable borrow is writing to the binding,
            # so one may not be taken of something that cannot be written.
            name = expr.expr.name
            frozen = self._frozen_vars.get(name)
            if frozen is not None and frozen != "moved":
                raise TypeError(
                    f"cannot mutably borrow {frozen} variable '{name}'")
            if self.env.is_const_global(name):
                raise TypeError(
                    f"cannot mutably borrow let variable '{name}'")

        val = unwrap_optional(self.eval_expr(expr.expr))
        if not (isinstance(val, ObjectValue)
                and isinstance(val.obj, ArrayValue)):
            kind = "&mut" if expr.is_mut else "&"
            raise TypeError(
                f"foreach over {kind} requires an array, got "
                f"{self._value_type_name(val)}")
        array = val.obj
        return [ElementRef(array, i, expr.is_mut)
                for i in range(array.sizeof)]

    def _resolve_iterable(self, expr, is_comptime: bool = False) -> list[Value]:
        """Resolve an expression to a list of values for foreach iteration."""
        val = unwrap_optional(self.eval_expr(expr))
        if isinstance(val, RangeValue):
            return [mk_int(i) for i in val.to_list()]
        if isinstance(val, ObjectValue) and isinstance(val.obj, ArrayValue):
            return val.obj.values()
        if is_comptime and isinstance(val, TupleValue):
            return list(val.elements)
        raise TypeError(
            f"foreach requires range or iterable, got {type(val).__name__}")

    def _eval_expect(self, node: ExpectStmt):
        """Evaluate a statement wrapped in @expect annotations.

        Captures errors and warnings produced by the inner statement and
        matches them against the expected patterns.  Raises TypeError if
        any expectation remains unmatched.
        """
        diagnostics: list[tuple[str, str]] = []
        # Warnings found before the program ran, about this statement.
        diagnostics.extend(
            ("warning", w) for w in getattr(node.stmt, "static_warnings", ()))
        saved_warnings = self._warnings
        self._warnings = []
        try:
            self.eval_stmt(node.stmt)
        except Exception as e:
            diagnostics.append(("error", str(e)))
        diagnostics.extend(("warning", w) for w in self._warnings)
        self._warnings = saved_warnings

        remaining = list(node.expectations)
        for level, msg in diagnostics:
            for i, (exp_level, exp_pattern) in enumerate(remaining):
                if level == exp_level and re.search(exp_pattern, msg):
                    remaining.pop(i)
                    break

        if remaining:
            unmatched = "; ".join(
                f"@expect {lv} \"{pat}\"" for lv, pat in remaining)
            if diagnostics:
                got = "; ".join(f"{lv}: {msg}" for lv, msg in diagnostics)
                raise TypeError(
                    f"unmatched expectations: {unmatched} (actual: {got})")
            raise TypeError(
                f"expected diagnostics not produced: {unmatched}")
        return none()

    # ------------------------------------------------------------------
    # Catch statement (scoped error handling)
    # ------------------------------------------------------------------

    def _eval_match(self, node: MatchStmt):
        """Dispatch on the shape of a value.

        An optional matches ∃(name), which binds the value it holds, or
        ∅ when it holds nothing.  A `_` arm matches anything.  The bound
        name exists only for its arm, and cannot be assigned to: it
        names the matched value, and writing to it would say nothing
        about the value that was matched.
        """
        subject = self.eval_expr(node.subject)

        # A sum type is matched by naming an alternative, so the arm to
        # run is the one whose type the value actually has.
        if any(arm.kind == "type" for arm in node.arms):
            return self._eval_match_by_type(node, subject)

        shape, inner = self._match_shape(subject)

        for arm in node.arms:
            if arm.kind == "wildcard":
                return self.eval_stmts(arm.body)
            if arm.kind != shape:
                continue
            if arm.kind == "none":
                return self.eval_stmts(arm.body)
            # ∃(name) or ∄(name), both of which bind.
            old_frozen = self._frozen_vars.get(arm.name)
            self.env.define(arm.name, inner)
            self._frozen_vars[arm.name] = "match"
            try:
                return self.eval_stmts(arm.body)
            finally:
                if old_frozen is None:
                    self._frozen_vars.pop(arm.name, None)
                else:
                    self._frozen_vars[arm.name] = old_frozen

        described = {"some": "a present value",
                     "none": "\N{EMPTY SET}",
                     "err": "a failed result"}[shape]
        raise TypeError(
            f"match has no arm for {described}; add the missing pattern "
            f"or a _ arm")

    @staticmethod
    def _written_type(expr) -> str | None:
        """The type an expression writes, or None if it writes a value.

        `i32` and `i32[4]` name types; a variable of either does not,
        even where the two are spelled alike.
        """
        if isinstance(expr, VarRef):
            return expr.name if is_type_name(expr.name) else None
        if isinstance(expr, Subscript) and isinstance(expr.obj, VarRef) \
                and is_type_name(expr.obj.name):
            dims = []
            for index in expr.indices:
                if not isinstance(index, IntLit):
                    return None
                dims.append(str(index.value))
            return f"{expr.obj.name}[{','.join(dims)}]"
        return None

    def _type_byte_size(self, type_name: str):
        """The storage a type occupies, in bytes."""
        from interp.layout import LayoutError, struct_lookup, type_layout
        from interp.units import BUILTIN_UNITS
        try:
            size, _ = type_layout(type_name, struct_lookup(self.env))
        except LayoutError as e:
            raise TypeError(f"@sizeof: {e}") from None
        return UnitValue(mk_int(size), BUILTIN_UNITS["byte"])

    @staticmethod
    def _describe_operand(expr) -> str:
        """Name an operand for a diagnostic, however it was written."""
        return f"'{expr.name}'" if isinstance(expr, VarRef) else "the operand"

    def _names_a_binding(self, expr) -> bool:
        """Whether an expression can be asked about its type.

        A binding's type is static information even where its value is
        not, so `@typeof` can answer for one.  So can an expression
        built from bindings and operators: working it out changes
        nothing, and its type follows from theirs.

        A call is where that stops.  Its type may well be static, but
        reaching it here would mean running the function, and a
        question about a type must not do that.
        """
        if isinstance(expr, VarRef):
            try:
                self.env.lookup(expr.name)
            except KeyError:
                return False
            return True
        if isinstance(expr, (IntLit, FloatLit, StrLit, BoolLit, NoneLit)):
            return True
        if isinstance(expr, BinOp):
            return (self._names_a_binding(expr.left)
                    and self._names_a_binding(expr.right))
        if isinstance(expr, UnaryOp):
            return self._names_a_binding(expr.operand)
        if isinstance(expr, WrapExpr):
            return self._names_a_binding(expr.expr)
        if isinstance(expr, UnitExpr):
            return self._names_a_binding(expr.expr)
        if isinstance(expr, Subscript):
            return (self._names_a_binding(expr.obj)
                    and all(self._names_a_binding(i) for i in expr.indices))
        if isinstance(expr, GetAttr):
            return self._names_a_binding(expr.obj)
        return False

    def _eval_match_by_type(self, node: MatchStmt, subject: Value):
        """Run the arm naming the alternative the value actually is."""
        actual = runtime_type_of(unwrap_optional(subject))
        for arm in node.arms:
            if arm.kind == "wildcard":
                return self.eval_stmts(arm.body)
            if arm.kind != "type" or arm.type_name != actual:
                continue
            return self._eval_bound_arm(arm, subject)
        raise TypeError(
            f"match has no arm for {actual}; add the missing pattern "
            f"or a _ arm")

    def _eval_bound_arm(self, arm, value: Value):
        """Run an arm with its name bound to the matched value.

        The name exists only for its arm and cannot be assigned to: it
        names the matched value, and writing to it would say nothing
        about the value that was matched.
        """
        old_frozen = self._frozen_vars.get(arm.name)
        self.env.define(arm.name, value)
        self._frozen_vars[arm.name] = "match"
        try:
            return self.eval_stmts(arm.body)
        finally:
            if old_frozen is None:
                self._frozen_vars.pop(arm.name, None)
            else:
                self._frozen_vars[arm.name] = old_frozen

    @staticmethod
    def _match_shape(subject):
        """Classify a match subject, and give the value an arm would bind.

        ∃ covers both a present optional and a successful result: in each
        the question "was there a value" is answered yes.  ∄ is the
        failed result, which answers no and says why; ∅ is the absent
        optional, which answers no and does not.
        """
        if isinstance(subject, ExpectedValue):
            if subject.is_ok():
                return "some", subject.ok_value
            return "err", subject.err_value
        if isinstance(subject, NoneValue):
            return "none", subject
        if isinstance(subject, SomeValue):
            return "some", subject.value
        return "some", subject

    def _eval_catch(self, node: CatchStmt):
        """Evaluate a catch block: catch errors from direct operations.

        Errors from function calls are wrapped in _PropagatedError by
        _do_call and pass through uncaught (syntactic scope only).
        """
        if not self._current_ret_type:
            raise TypeError(
                "catch requires enclosing function to have optional or expected return type")
        _, opt_err = _split_optional_type(self._current_ret_type)
        if opt_err is None:
            raise TypeError(
                "catch requires enclosing function to have optional or expected return type")

        self._catch_depth += 1
        try:
            return self.eval_stmts(node.body)
        except _ReturnSentinel:
            raise
        except _PropagatedError:
            raise
        except Exception as e:
            raise _ReturnSentinel(self._error_to_return(e))
        finally:
            self._catch_depth -= 1

    def _error_to_return(self, error: Exception) -> Value:
        """Convert a caught runtime error to the appropriate return value."""
        _, opt_err = _split_optional_type(self._current_ret_type)
        if opt_err is not None and opt_err != "":
            return ExpectedValue.err(self._map_error_to_enum(error))
        return none()

    def _map_error_to_enum(self, error: Exception) -> Value:
        """Map a Python exception to a std.errors enum value."""
        try:
            std_val = self.env.lookup("std")
            if isinstance(std_val, ObjectValue):
                errors_enum = getattr(std_val.obj, "errors", None)
                if isinstance(errors_enum, EnumType):
                    if isinstance(error, IndexError):
                        return EnumValue(errors_enum, errors_enum.members["index_out_of_range"])
                    if isinstance(error, OverflowError):
                        return EnumValue(errors_enum, errors_enum.members["integer_overflow"])
                    if isinstance(error, TypeError):
                        return EnumValue(errors_enum, errors_enum.members["type_mismatch"])
        except Exception:
            pass
        return mk_str(str(error))

    # ------------------------------------------------------------------
    # Reshape (⍴) operator
    # ------------------------------------------------------------------

    def _eval_reshape(self, shape_val: Value, data_val: Value) -> Value:
        """Evaluate shape ⍴ data — reshape data to the given dimensions."""
        su = unwrap_optional(shape_val)
        du = unwrap_optional(data_val)

        if isinstance(su, IntValue):
            dims = [su.value]
        elif isinstance(su, TupleValue):
            dims: list[int] = []
            for d in su.elements:
                dv = unwrap_optional(d)
                if not isinstance(dv, IntValue):
                    raise TypeError(
                        "\N{APL FUNCTIONAL SYMBOL RHO}: dimensions must be integers")
                dims.append(dv.value)
            if len(dims) > MAX_TENSOR_RANK:
                raise TypeError(
                    f"\N{APL FUNCTIONAL SYMBOL RHO}: too many dimensions "
                    f"({len(dims)}), maximum is {MAX_TENSOR_RANK}")
        else:
            raise TypeError(
                f"\N{APL FUNCTIONAL SYMBOL RHO}: left operand must be integer "
                f"or tuple, got {type(su).__name__}")

        for d in dims:
            if d < 0:
                raise TypeError(
                    "\N{APL FUNCTIONAL SYMBOL RHO}: dimensions must be non-negative")

        source: list[Value]
        backing: list[Value] | None = None
        etype: str | None = None
        if isinstance(du, IntValue):
            source = [du]
        elif isinstance(du, ObjectValue) and isinstance(du.obj, ArrayValue):
            arr = du.obj
            etype = arr.element_type
            if arr._backing is not None:
                backing = arr._backing
                source = backing[arr._offset:arr._offset + arr._length]
            else:
                backing = arr.elements
                source = backing
            if not source:
                raise TypeError(
                    "\N{APL FUNCTIONAL SYMBOL RHO}: cannot reshape empty array")
        elif isinstance(du, RangeValue):
            source = [mk_int(i) for i in du.to_list()]
            if not source:
                raise TypeError(
                    "\N{APL FUNCTIONAL SYMBOL RHO}: cannot reshape empty range")
        else:
            raise TypeError(
                f"\N{APL FUNCTIONAL SYMBOL RHO}: cannot reshape "
                f"{type(du).__name__}")

        total = 1
        for d in dims:
            total *= d
        if total == 0:
            if len(dims) == 1:
                return ObjectValue(ArrayValue([], element_type=etype))
            return ObjectValue(ArrayValue([]))

        if backing is not None and total <= len(source) and len(dims) > 1:
            return self._build_view(dims, backing, etype, 0)
        return self._build_shaped(dims, source, etype, 0)

    @staticmethod
    def _build_shaped(dims: list[int], source: list[Value],
                      etype: str | None, offset: int) -> ObjectValue:
        """Recursively build a shaped array from cycling source elements."""
        if len(dims) == 1:
            n = dims[0]
            elements = [source[(offset + i) % len(source)] for i in range(n)]
            return ObjectValue(ArrayValue(elements, element_type=etype))
        n = dims[0]
        inner_size = 1
        for d in dims[1:]:
            inner_size *= d
        rows: list[Value] = []
        for i in range(n):
            row = Evaluator._build_shaped(
                dims[1:], source, etype, offset + i * inner_size)
            rows.append(row)
        return ObjectValue(ArrayValue(rows))

    @staticmethod
    def _build_view(dims: list[int], backing: list[Value],
                    etype: str | None, offset: int) -> ObjectValue:
        """Build a shaped view sharing the backing list."""
        if len(dims) == 1:
            return ObjectValue(ArrayValue(
                backing=backing, offset=offset, length=dims[0],
                element_type=etype))
        n = dims[0]
        inner_size = 1
        for d in dims[1:]:
            inner_size *= d
        rows: list[Value] = []
        for i in range(n):
            row = Evaluator._build_view(
                dims[1:], backing, etype, offset + i * inner_size)
            rows.append(row)
        return ObjectValue(ArrayValue(rows))

    # ------------------------------------------------------------------
    # Fold operators
    # ------------------------------------------------------------------

    def _eval_fold(self, node: FoldExpr) -> Value:
        """Evaluate a fold expression: left fold ⌿ or right fold ⍀."""
        func = self.eval_expr(node.func)
        container_val = self.eval_expr(node.container)

        cu = unwrap_optional(container_val)
        if isinstance(cu, RangeValue):
            elements = [mk_int(i) for i in cu.to_list()]
        elif isinstance(cu, ObjectValue) and isinstance(cu.obj, ArrayValue):
            elements = cu.obj.values()
        else:
            raise TypeError(
                f"fold requires array or range, got {type(cu).__name__}")

        if node.init is not None:
            acc = self.eval_expr(node.init)
        else:
            if not elements:
                raise TypeError("fold on empty container requires an initial value")
            if node.direction == "left":
                acc = elements[0]
                elements = elements[1:]
            else:
                acc = elements[-1]
                elements = elements[:-1]

        if node.direction == "left":
            for elem in elements:
                acc = self._do_call(func, [acc, elem])
        else:
            for elem in reversed(elements):
                acc = self._do_call(func, [elem, acc])
        return acc

    # ------------------------------------------------------------------
    # Lambda support
    # ------------------------------------------------------------------

    @staticmethod
    def _is_builtin_value(val: Value) -> bool:
        """Check if a value doesn't need explicit capture in a lambda.

        Builtins, enum types, module objects, and non-replaceable
        user-defined functions are always accessible.
        """
        if isinstance(val, (BuiltinFunc, EnumType, StructType)):
            return True
        if isinstance(val, FuncValue) and not val.is_replaceable:
            return True
        if isinstance(val, ObjectValue) and not isinstance(val.obj, ArrayValue):
            return True
        return False

    @staticmethod
    def _value_type_name(val: Value) -> str:
        """Return the type name string for a runtime value."""
        if isinstance(val, ElementRef):
            prefix = "&mut " if val.is_mut else "&"
            return prefix + Evaluator._value_type_name(val.get())
        if isinstance(val, RefValue):
            return "&mut " + Evaluator._value_type_name(val.get())
        u = unwrap_optional(val)
        if isinstance(u, UnitValue):
            return Evaluator._value_type_name(u.inner)
        if isinstance(u, IntValue):
            return u.width
        if isinstance(u, FloatValue):
            return u.width
        if isinstance(u, StrValue):
            return "str"
        if isinstance(u, BoolValue):
            return "bool"
        if isinstance(u, NoneValue):
            return "\N{EMPTY SET}"
        if isinstance(u, SomeValue):
            return Evaluator._value_type_name(u.value) + "?"
        if isinstance(u, ExpectedValue):
            if u.is_ok():
                return Evaluator._value_type_name(u.ok_value) + "!"
            return "err"
        if isinstance(u, FuncValue):
            return "fn"
        if isinstance(u, LambdaValue):
            return "\N{GREEK SMALL LETTER LAMDA}"
        if isinstance(u, BuiltinFunc):
            return "builtin"
        if isinstance(u, TupleValue):
            return "tuple"
        if isinstance(u, EnumValue):
            return u.enum_type.name
        if isinstance(u, ObjectValue) and isinstance(u.obj, StructInstance):
            return u.obj.struct_type.name
        if isinstance(u, ObjectValue) and isinstance(u.obj, ArrayValue):
            return "array"
        if isinstance(u, RangeValue):
            return "range"
        if isinstance(u, TypeValue):
            return "type"
        return "unknown"

    def _eval_lambda_expr(self, node: LambdaExpr):
        """Evaluate a lambda expression: validate captures and build LambdaValue."""
        refs = _collect_refs(node.body)
        refs -= {p[0] for p in node.params}

        lambda_env = Env()
        capture_set = set(node.captures) if node.captures else set()

        if node.captures is not None:
            for name in node.captures:
                try:
                    val = self.env.lookup(name)
                except KeyError:
                    raise TypeError(
                        f"lambda capture '{name}' is not defined")
                lambda_env.define(name, val)

        for name in refs:
            if name in capture_set:
                continue
            try:
                val = self.env.lookup(name)
            except KeyError:
                raise TypeError(
                    f"lambda references undefined name '{name}'")
            if self._is_builtin_value(val):
                lambda_env.define(name, val)
            else:
                if node.captures is not None:
                    raise TypeError(
                        f"lambda references '{name}' which is not "
                        f"in the capture list")
                raise TypeError(
                    f"lambda references '{name}' but has no capture list")

        return LambdaValue(node.params, node.body, lambda_env,
                           captures=node.captures, ret_type=node.ret_type)

    def _call_lambda(self, lam: LambdaValue, args):
        """Call a lambda value with given arguments."""
        if lam.partial_func is not None:
            all_args = list(lam.partial_args) + list(args)
            return self._call_user_func(lam.partial_func, all_args)

        if len(args) != len(lam.params):
            if len(args) < len(lam.params):
                remaining = lam.params[len(args):]
                new_env = Env(parent=lam.env)
                for (pname, _ptype), arg in zip(lam.params, args):
                    new_env.define(pname, arg)
                return LambdaValue(remaining, lam.body, new_env,
                                   captures=lam.captures, ret_type=lam.ret_type)
            raise TypeError(
                f"lambda expects {len(lam.params)} arguments, "
                f"got {len(args)}")

        call_env = Env(parent=lam.env)
        for (pname, ptype), arg in zip(lam.params, args):
            if ptype is not None:
                arg = coerce_arg(arg, ptype, "\N{GREEK SMALL LETTER LAMDA}", pname)
            call_env.define(pname, arg)

        old_env = self.env
        old_ret_type = self._current_ret_type
        try:
            self.env = call_env
            self._current_ret_type = lam.ret_type
            if isinstance(lam.body, list):
                result = self.eval_stmts(lam.body)
            else:
                result = self.eval_expr(lam.body)
            self._check_return_type(result, lam.ret_type, "\N{GREEK SMALL LETTER LAMDA}")
            return self._wrap_optional_return(result, lam.ret_type)
        except _ReturnSentinel as e:
            self._check_return_type(e.value, lam.ret_type, "\N{GREEK SMALL LETTER LAMDA}")
            return self._wrap_optional_return(e.value, lam.ret_type)
        finally:
            self.env = old_env
            self._current_ret_type = old_ret_type

    def _builtin_generate(self, args):
        """generate(func, range) — apply func to each value in range, return array."""
        if len(args) != 2:
            raise TypeError("generate(func, range) takes exactly 2 arguments")
        func, range_val = args
        if not isinstance(func, (FuncValue, LambdaValue, BuiltinFunc)):
            raise TypeError(
                f"generate: first argument must be a function, "
                f"got {type(func).__name__}")
        if not isinstance(range_val, RangeValue):
            raise TypeError(
                f"generate: second argument must be a range, "
                f"got {type(range_val).__name__}")
        elements: list[Value] = []
        for i in range_val.to_list():
            result = self._do_call(func, [mk_int(i)])
            if is_none(result):
                raise TypeError(
                    "generate: function must not return \N{EMPTY SET}")
            elements.append(result)
        return ObjectValue(ArrayValue(elements))

    # ------------------------------------------------------------------
    # Struct literal evaluation
    # ------------------------------------------------------------------

    def _eval_struct_lit(self, node: StructLit) -> Value:
        """Evaluate a struct literal: Name { field: expr, ... }."""
        try:
            struct_type = self.env.lookup(node.name)
        except KeyError:
            raise TypeError(f"unknown struct type '{node.name}'")
        if not isinstance(struct_type, StructType):
            raise TypeError(f"'{node.name}' is not a struct type")
        field_values: dict[str, Value] = {}
        for field_name, field_expr in node.field_inits:
            found_type = None
            for fname, ftype in struct_type.fields:
                if fname == field_name:
                    found_type = ftype
                    break
            if found_type is None:
                raise TypeError(
                    f"struct '{node.name}' has no field '{field_name}'")
            value = self.eval_expr(field_expr)
            value = coerce_arg(value, found_type, node.name, field_name)
            field_values[field_name] = value
        for fname, ftype in struct_type.fields:
            if fname not in field_values:
                raise TypeError(
                    f"missing field '{fname}' in struct '{node.name}' literal")
        return ObjectValue(StructInstance(struct_type, field_values))

    # ------------------------------------------------------------------
    # Function calls
    # ------------------------------------------------------------------

    def _call_func(self, name: str, args):
        """Call a function by name with given arguments.

        Looks up the function in the environment, dispatching to user-defined
        functions (FuncValue) or builtins (BuiltinFunc/BuiltinBoundMethod).
        """
        func = self.env.lookup(name)
        return self._do_call(func, args)

    def _call_method(self, obj: Value, method_name: str, args):
        """Call a method on an object value.

        For builtin-style methods (like StdModule.sha256(args)) that accept a
        single list of already-evaluated Values, we detect this by checking the
        method signature — if it has exactly one parameter named "args" after
        self, we pass the list as-is.  Otherwise we unpack args for ordinary
        Python methods like ``fs.cwd()``.
        """
        import inspect

        unwrapped = unwrap_optional(obj)
        if method_name == "__call__":
            return self._do_call(unwrapped, args)
        if isinstance(unwrapped, Iterator):
            if method_name != "next":
                raise AttributeError(
                    f"an iterator has no method '{method_name}'; it answers "
                    f"only next()")
            if args:
                raise TypeError("iterator.next takes no arguments")
            return unwrapped.next()
        # callstack reads evaluator state, which a plain method on the
        # std object has no way to reach.
        if (method_name == "callstack" and isinstance(unwrapped, ObjectValue)
                and unwrapped.obj is std):
            return self._callstack_value(args)
        if (isinstance(unwrapped, ObjectValue)
                and isinstance(unwrapped.obj, ArrayValue)
                and method_name in _ARRAY_METHODS):
            return self._call_array_method(unwrapped.obj, method_name, args)
        if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, StructInstance):
            inst = unwrapped.obj
            method = inst.struct_type.methods.get(method_name)
            if method is not None:
                if method.params and method.params[0][0] == "self":
                    return self._call_user_func(method, [unwrapped] + list(args))
                return self._call_user_func(method, list(args))
            raise AttributeError(
                f"struct '{inst.struct_type.name}' has no method '{method_name}'")
        if isinstance(unwrapped, StructType):
            if method_name == "offsetof":
                return self._struct_offsetof(unwrapped, args)
            method = unwrapped.methods.get(method_name)
            if method is not None:
                return self._call_user_func(method, list(args))
            raise AttributeError(
                f"struct '{unwrapped.name}' has no static method '{method_name}'")
        if isinstance(unwrapped, ObjectValue):
            python_obj = unwrapped.obj
            meth = getattr(python_obj, method_name, None)
            if meth is not None and callable(meth):
                # Detect builtin-style method: takes exactly one "args" list.
                try:
                    sig = inspect.signature(meth)
                    params = list(sig.parameters.values())
                    is_builtin_style = (
                        len(params) == 1 and params[0].name == "args"
                    )
                except (ValueError, TypeError):
                    # Some builtins don't have signatures — default to unpacking.
                    is_builtin_style = False

                if is_builtin_style:
                    result = meth(args)
                else:
                    # Unwrap Values for normal Python method calls.
                    py_args = []
                    for a in args:
                        au = unwrap_optional(a)
                        if isinstance(au, StrValue):
                            py_args.append(au.value)
                        elif isinstance(au, IntValue):
                            py_args.append(au.value)
                        elif isinstance(au, BoolValue):
                            py_args.append(au.value)
                        elif isinstance(au, ObjectValue):
                            py_args.append(au.obj)
                        else:
                            py_args.append(a)
                    result = meth(*py_args)

                # Wrap non-Value results in ObjectValue.
                if not isinstance(result, Value):
                    return self._track_temporary(ObjectValue(result))
                return result

        # Fallback: try the original value's attribute.
        meth = getattr(obj, method_name, None)
        if meth is not None and callable(meth):
            try:
                sig = inspect.signature(meth)
                params = list(sig.parameters.values())
                is_builtin_style = (
                    len(params) == 1 and params[0].name == "args"
                )
            except (ValueError, TypeError):
                is_builtin_style = False

            if is_builtin_style:
                result = meth(args)
            else:
                py_args = []
                for a in args:
                    au = unwrap_optional(a)
                    if isinstance(au, StrValue):
                        py_args.append(au.value)
                    elif isinstance(au, IntValue):
                        py_args.append(au.value)
                    elif isinstance(au, BoolValue):
                        py_args.append(au.value)
                    elif isinstance(au, ObjectValue):
                        py_args.append(au.obj)
                    else:
                        py_args.append(a)
                result = meth(*py_args)

            if not isinstance(result, Value):
                return self._track_temporary(ObjectValue(result))
            return result

        raise AttributeError(f"no method '{method_name}' on {type(obj).__name__}")

    def _do_call(self, func: Value, args):
        """Dispatch a call to either user-defined, lambda, or builtin function.

        When inside a catch scope (_catch_depth > 0), exceptions from the
        called function are wrapped in _PropagatedError so that the catch
        block can distinguish them from direct-operation errors.
        """
        try:
            if isinstance(func, FuncValue):
                return self._call_user_func(func, args)
            if isinstance(func, LambdaValue):
                return self._call_lambda(func, args)
            if isinstance(func, BuiltinFunc):
                if func.name == "generate":
                    return self._builtin_generate(args)
                expected = func.arity
                if expected != -1 and len(args) != expected:
                    raise TypeError(
                        f"{func.name} expects {expected} arguments, got {len(args)}")
                return func.func(args)
            if isinstance(func, BuiltinBoundMethod):
                return func(*args)
            raise TypeError(f"cannot call {type(func).__name__}")
        except (_ReturnSentinel, _PropagatedError):
            raise
        except Exception as e:
            if self._catch_depth > 0:
                raise _PropagatedError(e) from e
            raise

    def _call_user_func(self, func: FuncValue, args):
        """Call a user-defined function with proper scoping."""
        if func.name in self._test_hooks:
            pending = self._test_hooks.pop(func.name)
            for test_fv in pending:
                if test_fv.name not in self._tests_run:
                    self._tests_run.add(test_fv.name)
                    self._call_user_func(test_fv, [])

        n_regular = len(func.params)
        has_pack = func.pack_param is not None

        if len(args) < n_regular:
            remaining = func.params[len(args):]
            return LambdaValue(remaining, func.body, self.env,
                               partial_func=func, partial_args=list(args))
        if not has_pack and len(args) != n_regular:
            raise TypeError(
                f"{func.name} expects {n_regular} arguments, got {len(args)}")

        regular_args = args[:n_regular]
        pack_args = args[n_regular:] if has_pack else []

        resolved_params = func.params
        resolved_ret_type = func.ret_type
        resolved_pack_type = func.pack_param[1] if has_pack else None

        all_typed_params = list(func.params)
        if has_pack and func.pack_param[1] is not None:
            all_typed_params.append(func.pack_param)

        has_generics = any(
            pt is not None and is_generic_type(pt) for _, pt in all_typed_params
        ) or (func.ret_type is not None and is_generic_type(func.ret_type))

        generic_map: dict[str, str] = {}
        if has_generics:
            for (pname, ptype), arg in zip(func.params, regular_args):
                if ptype is None:
                    continue
                gname = _extract_generic_name(ptype)
                if gname is None:
                    continue
                concrete = _resolve_concrete_for_generic(ptype, arg)
                if gname in generic_map:
                    if generic_map[gname] != concrete:
                        raise TypeError(
                            f"{func.name}: generic type {gname} resolved to "
                            f"'{generic_map[gname]}' but argument '{pname}' "
                            f"has type '{concrete}'")
                else:
                    generic_map[gname] = concrete

            resolved_params = [
                (n, _substitute_generics(t, generic_map) if t else t)
                for n, t in func.params
            ]
            if func.ret_type is not None:
                resolved_ret_type = _substitute_generics(func.ret_type, generic_map)
            if resolved_pack_type is not None:
                resolved_pack_type = _substitute_generics(resolved_pack_type, generic_map)

        call_env = func.env.copy_for_call()
        for (param_name, param_type), arg_value in zip(resolved_params, regular_args):
            self._check_resizable_argument(func, param_name, param_type,
                                           arg_value)
            is_ref_param = param_name in func.param_refs
            if is_ref_param:
                if not isinstance(arg_value, RefValue):
                    raise TypeError(
                        f"{func.name}: parameter '{param_name}' is by-reference, "
                        f"caller must pass &{param_name}")
                call_env.define(param_name, arg_value)
                continue
            if isinstance(arg_value, RefValue):
                raise TypeError(
                    f"{func.name}: parameter '{param_name}' is by-value, "
                    f"caller must not pass a reference")
            arg_value = deep_copy_value(arg_value)
            # The copy takes the parameter's shape: a dynamically-sized
            # parameter yields a dynamic array whatever it was given, as
            # `let d : mut i32[] = f` does.
            if param_type is not None and isinstance(arg_value, ObjectValue) \
                    and isinstance(arg_value.obj, ArrayValue):
                declared = _parse_array_type(param_type)
                if declared is not None:
                    arg_value.obj.fixed_size = declared[1][0]
            if param_name in func.param_units:
                from interp.units import eval_unit_formula
                unit = eval_unit_formula(func.param_units[param_name])
                if isinstance(arg_value, UnitValue):
                    arg_value = self._convert_unit_value(arg_value, unit)
                elif isinstance(arg_value, IntValue) and arg_value.width != "int":
                    raise TypeError(
                        f"{func.name}: parameter '{param_name}' requires unit "
                        f"{unit.display_name}, got typed integer "
                        f"{arg_value.width} without unit")
                else:
                    arg_value = UnitValue(arg_value, unit)
            if param_type is not None:
                if isinstance(arg_value, UnitValue) and param_name in func.param_units:
                    inner = coerce_arg(arg_value.inner, param_type,
                                       func.name, param_name)
                    arg_value = UnitValue(inner, arg_value.unit)
                else:
                    arg_value = coerce_arg(arg_value, param_type,
                                           func.name, param_name)
            call_env.define(param_name, arg_value)

        if has_pack:
            pack_name = func.pack_param[0]
            pack_elements = []
            for i, parg in enumerate(pack_args):
                if resolved_pack_type is not None and not is_generic_type(resolved_pack_type):
                    parg = coerce_arg(parg, resolved_pack_type, func.name,
                                      f"{pack_name}[{i}]")
                pack_elements.append(parg)
            call_env.define(pack_name, TupleValue(pack_elements))

        old_env = self.env
        old_ret_type = self._current_ret_type
        old_pure = self._pure_func_name
        old_frozen = self._frozen_vars.copy()
        old_generic_map = self._generic_map
        old_comptime_vars = self._comptime_vars
        for param_name, _ in func.params:
            # Only `mut` grants the right to write, whether the value
            # came by value or by reference.  A plain `&T` is a shared
            # borrow: it says where the value lives, not that the callee
            # may change it.  `&mut T` is the one that may.
            if param_name in func.param_muts:
                continue
            self._frozen_vars[param_name] = (
                "borrowed" if param_name in func.param_refs else "let")
        self._call_stack.append([func.name, self._last_pos, func.source_label])
        returned: Value | None = None
        # Parameters hold values the caller owns, so leaving this scope
        # must not destroy them.
        borrowed = {name for name, _ in func.params}
        if has_pack:
            borrowed.add(func.pack_param[0])
        try:
            self.env = call_env
            self._current_ret_type = resolved_ret_type
            self._pure_func_name = None if func.is_impure else func.name
            self._generic_map = generic_map
            self._comptime_vars = {n for n, _ in func.params}
            if has_pack:
                self._comptime_vars.add(func.pack_param[0])
            result = self.eval_stmts(func.body)
            result = self._check_return_type(
                result, resolved_ret_type, func.name, func.ret_unit)
            returned = self._wrap_optional_return(result, resolved_ret_type)
            return returned
        except _ReturnSentinel as e:
            checked = self._check_return_type(
                e.value, resolved_ret_type, func.name, func.ret_unit)
            returned = self._wrap_optional_return(checked, resolved_ret_type)
            return returned
        except _PropagatedError as pe:
            raise pe.original from pe
        except BaseException as e:
            # Attach the stack to the exception itself, at the innermost
            # frame that sees it, so it survives the unwinding below and
            # cannot be confused with a later, unrelated failure.
            attach_backtrace(e, self._call_stack)
            raise
        finally:
            self._end_scope(call_env, returned, borrowed)
            self._call_stack.pop()
            self.env = old_env
            self._current_ret_type = old_ret_type
            self._pure_func_name = old_pure
            self._frozen_vars = old_frozen
            self._generic_map = old_generic_map
            self._comptime_vars = old_comptime_vars

    def _track_temporary(self, value):
        """Note a freshly produced resource so an unkept one can be released.

        A resource that is never assigned to anything has no binding to
        own it and no scope to end, so without this it would survive
        until the program exits.  `std.fs.cwd().open_file(name)` is the
        motivating case: the directory exists only to reach the file.
        """
        if self._temporaries is not None and isinstance(value, ObjectValue):
            if callable(getattr(value.obj, "destroy", None)):
                self._temporaries.append(value.obj)
        return value

    def _release_temporaries(self, result):
        """Destroy resources this statement produced and did not keep.

        A temporary is kept when the statement bound it to a name or when
        it is the statement's own value, which the surrounding expression
        or the caller may still be about to use.  Everything else was
        needed only while the statement ran.

        Args:
            result: the value the statement produced, if it completed.
        """
        temporaries = self._temporaries
        if not temporaries:
            return

        kept = set()
        for value in (result, result.value if isinstance(result, SomeValue) else None):
            if isinstance(value, ObjectValue):
                kept.add(id(value.obj))
        # Anything the statement bound to a name is owned by that binding
        # now, and is released when its scope ends instead.
        for frame in self.env._frames:
            for bound in frame.values():
                if isinstance(bound, ObjectValue):
                    kept.add(id(bound.obj))

        for obj in reversed(temporaries):
            if id(obj) in kept:
                continue
            kept.add(id(obj))
            try:
                obj.destroy()
            except Exception as e:
                self._warnings.append(f"releasing a temporary failed: {e}")

    def _end_scope(self, call_env, returned, borrowed: set[str]):
        """Destroy the resources a departing scope owns.

        A value that holds an operating system resource -- an open file,
        for now -- is owned by the binding it was assigned to, and is
        released when that binding's scope ends, however it ends.
        Bindings are destroyed in reverse order of definition, so a
        resource acquired using an earlier one is released first.

        Two kinds of binding are left alone.  Parameters name values the
        caller owns.  The returned value is handed to the caller, which
        takes ownership with it -- destroying it here would give the
        caller a closed file.

        A destructor that fails becomes a warning rather than an error:
        the scope is already being left, and in the common case it is
        being left because something else went wrong.

        Args:
            call_env: the environment whose local frame is ending.
            returned: the value being handed to the caller, if any.
            borrowed: names of bindings this scope does not own.
        """
        frame = call_env._frames[-1]
        if not frame:
            return

        # Look through an optional or a successful expected to find the
        # object that is really escaping.  unwrap_optional is not usable
        # here: it raises for an expected holding an error, which is an
        # ordinary way for a function to return.
        escaping = set()
        candidates = [returned]
        if isinstance(returned, SomeValue):
            candidates.append(returned.value)
        elif isinstance(returned, ExpectedValue) and returned.is_ok():
            candidates.append(returned.ok_value)
        for value in candidates:
            if isinstance(value, ObjectValue):
                escaping.add(id(value.obj))

        for name in reversed(list(frame)):
            if name in borrowed:
                continue
            value = frame[name]
            if not isinstance(value, ObjectValue):
                continue
            destroy = getattr(value.obj, "destroy", None)
            if not callable(destroy) or id(value.obj) in escaping:
                continue
            # Two bindings can name the same resource; destroying it once
            # is enough, and each destructor tolerates being run twice.
            escaping.add(id(value.obj))
            try:
                destroy()
            except Exception as e:
                self._warnings.append(
                    f"destroying '{name}' at end of scope failed: {e}")

    def _check_return_unit(self, result: Value, ret_type: str,
                           func_name: str, ret_unit) -> Value:
        """Verify a return value against a return type that states a unit.

        A bare number takes the unit, as it would at a parameter that
        states one.  A value already carrying a unit has to carry that
        one, since a unit is part of the type rather than a label.
        """
        from interp.units import eval_unit_formula
        want = eval_unit_formula(ret_unit)
        inner = result
        wrap = None
        if isinstance(inner, SomeValue):
            inner, wrap = inner.value, SomeValue
        elif isinstance(inner, NoneValue):
            return result
        elif isinstance(inner, ExpectedValue):
            if not inner.is_ok():
                return result
            inner, wrap = inner.ok_value, ExpectedValue.ok
        if isinstance(inner, UnitValue):
            if not inner.unit.same_dimension(want):
                raise TypeError(
                    f"{func_name}: return type is {ret_type} "
                    f"\N{CURRENCY SIGN}{want.display_name}, but the body evaluates to "
                    f"{inner.unit.display_name}")
            settled = self._convert_unit_value(inner, want)
        else:
            settled = UnitValue(inner, want)
        return wrap(settled) if wrap is not None else settled

    def _check_return_type(self, result: Value, ret_type: str | None,
                           func_name: str, ret_unit=None) -> Value:
        """Verify the return value matches the declared return type."""
        if ret_type is None or ret_type == "\N{EMPTY SET}":
            return result
        if ret_unit is not None:
            return self._check_return_unit(result, ret_type, func_name,
                                           ret_unit)
        base, opt_err = _split_optional_type(ret_type)
        check = base if opt_err is not None else ret_type
        if not check or check == "\N{EMPTY SET}":
            return result
        inner = result
        if isinstance(inner, SomeValue):
            inner = inner.value
        elif isinstance(inner, ExpectedValue):
            if inner.is_ok():
                inner = inner.ok_value
            else:
                return result
        elif isinstance(inner, NoneValue):
            return result
        # A return type states no unit, so a value carrying one is not
        # the type promised.  Parting with a unit is a real change and
        # is said rather than done quietly on the way out.
        if isinstance(inner, UnitValue):
            raise TypeError(
                f"{func_name}: return type is {ret_type}, but the body "
                f"evaluates to {inner.unit.display_name}; "
                f"use @dropunit to part with the unit")
        if check in _TYPE_BITS or check == "int":
            if isinstance(inner, FloatValue):
                raise TypeError(
                    f"{func_name}: return type is {ret_type} "
                    f"but body evaluates to {inner.width}")
            if isinstance(inner, (StrValue, BoolValue)):
                raise TypeError(
                    f"{func_name}: return type is {ret_type} "
                    f"but body evaluates to {self._value_type_name(inner)}")
            if isinstance(inner, IntValue):
                return coerce_to_type(inner, check) if opt_err is None else result
        elif check in FLOAT_TYPES:
            if isinstance(inner, IntValue):
                raise TypeError(
                    f"{func_name}: return type is {ret_type} "
                    f"but body evaluates to {inner.width}")
            if isinstance(inner, (StrValue, BoolValue)):
                raise TypeError(
                    f"{func_name}: return type is {ret_type} "
                    f"but body evaluates to {self._value_type_name(inner)}")
        elif check == "str":
            if not isinstance(inner, StrValue):
                raise TypeError(
                    f"{func_name}: return type is {ret_type} "
                    f"but body evaluates to {self._value_type_name(inner)}")
        elif check == "bool":
            if not isinstance(inner, BoolValue):
                raise TypeError(
                    f"{func_name}: return type is {ret_type} "
                    f"but body evaluates to {self._value_type_name(inner)}")
        return result

    def _wrap_optional_return(self, result: Value, ret_type: str | None) -> Value:
        """Wrap return value in SomeValue/ExpectedValue for optional/expected return types."""
        if not ret_type:
            return result
        base, opt_err = _split_optional_type(ret_type)
        if opt_err is None:
            return result
        if opt_err != "":
            if isinstance(result, ExpectedValue):
                return result
            if isinstance(result, NoneValue):
                return result
            if isinstance(result, IntValue) and base not in ("int", ""):
                result = mk_int(result.value, base)
            return ExpectedValue.ok(result)
        if isinstance(result, NoneValue):
            return result
        if isinstance(result, ExpectedValue):
            return result
        if isinstance(result, SomeValue):
            return result
        if isinstance(result, IntValue) and base not in ("int", ""):
            result = mk_int(result.value, base)
        return some(result)


class _ReturnSentinel(BaseException):
    """Internal sentinel for non-local return from functions.

    Carries the return value and is caught by eval_stmts to produce
    a clean return path without requiring exceptions in normal flow.
    """

    def __init__(self, value: Value):
        self.value = value


class _PropagatedError(Exception):
    """Wraps an exception from a function call inside a catch scope.

    When a catch block is active, errors from called functions are
    wrapped in this type so that _eval_catch can distinguish them
    from direct-operation errors and let them propagate uncaught.
    Unwrapped at function boundaries by _call_user_func.
    """

    def __init__(self, original: Exception):
        self.original = original
        super().__init__(str(original))
