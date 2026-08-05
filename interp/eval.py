"""Evaluator (interpreter) for the newlang language.

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
    IntLit, StrLit, BoolLit, NoneLit, VarRef, BinOp, UnaryOp,
    IfStmt, WhileStmt, ReturnStmt, FuncDef, VarDef, ExprStmt,
    FuncCall, MethodCall, OptSome, GetAttr,
    ArrayLit, Subscript, SliceAccess, ArrayAlloc, TryUnwrap,
    RangeExpr, ForEachStmt, ExpectStmt, WrapExpr, LambdaExpr,
    ReshapeExpr, TupleLit, CatchStmt, EnumerateExpr,
    StaticAssert, StaticAssertEq, TypeOfExpr, ResultOfExpr, SizeOfExpr, FoldExpr,
)
from interp.value import (
    Value, IntValue, StrValue, BoolValue, NoneValue, SomeValue, ExpectedValue,
    FuncValue, LambdaValue, BuiltinFunc, ObjectValue, BuiltinBoundMethod,
    ArrayValue, TupleValue, EnumType, EnumValue, RangeValue, TypeValue,
    mk_int, mk_int_wrap, mk_str, mk_bool, none, some, is_none, is_some,
    resolve_width, wrap_int, coerce_to_type, coerce_arg, _TYPE_BITS, FAST_TYPES,
    _split_optional_type, MAX_TENSOR_RANK,
    is_generic_type, runtime_type_of,
)
from interp.env import Env
from interp.std import std, DirFD, FileStream, Bytes, MmapAllocator


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
        refs |= _collect_refs(node.index)
    elif isinstance(node, SliceAccess):
        refs |= _collect_refs(node.obj)
        refs |= _collect_refs(node.start)
        refs |= _collect_refs(node.end)
    elif isinstance(node, ArrayLit):
        for e in node.elements:
            refs |= _collect_refs(e)
    elif isinstance(node, ArrayAlloc):
        refs |= _collect_refs(node.size_expr)
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
    return refs


def _is_const_expr(node) -> bool:
    """Check whether an AST node is a compile-time constant expression."""
    if isinstance(node, (IntLit, StrLit, BoolLit, NoneLit)):
        return True
    if isinstance(node, BinOp):
        return _is_const_expr(node.left) and _is_const_expr(node.right)
    if isinstance(node, UnaryOp):
        return _is_const_expr(node.operand)
    if isinstance(node, ArrayLit):
        return all(_is_const_expr(e) for e in node.elements)
    if isinstance(node, TupleLit):
        return all(_is_const_expr(e) for e in node.elements)
    if isinstance(node, (TypeOfExpr, ResultOfExpr, SizeOfExpr)):
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
        return value.value
    if isinstance(value, ExpectedValue):
        if value.is_ok():
            return value.ok_value
        raise TypeError(
            f"unwrap of expected error: {value.err_value.display()}")
    return value


def to_bool(value):
    """Convert a runtime Value to Python bool for control flow.

    Rules:
    - BoolValue → direct boolean
    - IntValue → truthy if non-zero
    - StrValue → truthy if non-empty
    - NoneValue → False
    - SomeValue → True (always, since it contains something)
    """
    if isinstance(value, BoolValue):
        return value.value
    if isinstance(value, IntValue):
        return value.value != 0
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
    """dir.openFile(name, mode?, flags?) — open file relative to directory."""
    if len(args) < 1 or len(args) > 3:
        raise TypeError("dir.openFile(name, mode?, flags?) takes 1-3 arguments")
    dir_fd = args[0]
    if isinstance(dir_fd, ObjectValue):
        dir_fd = dir_fd.obj
    name_arg = unwrap_optional(args[1])
    if not isinstance(name_arg, StrValue):
        raise TypeError(f"openFile expects string for name, got {type(name_arg).__name__}")
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


class Evaluator:
    """Evaluates newlang AST in a given environment.

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
        # Pre-compute builtin function mappings (avoid repeated lookups).
        self._ops = {
            "+": self._op_add,
            "-": self._op_sub,
            "*": self._op_mul,
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
        }

    # ------------------------------------------------------------------
    # Binary operators
    # ------------------------------------------------------------------

    def _op_add(self, left, right):
        """Addition: integers and strings (concatenation)."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return self._mk_int(lu.value + ru.value, resolve_width(lu.width, ru.width))
        if isinstance(lu, StrValue) and isinstance(ru, StrValue):
            return mk_str(lu.value + ru.value)
        raise TypeError(f"addition expected int+int or str+str, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_sub(self, left, right):
        """Subtraction."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return self._mk_int(lu.value - ru.value, resolve_width(lu.width, ru.width))
        raise TypeError(f"subtraction expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_mul(self, left, right):
        """Multiplication."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return self._mk_int(lu.value * ru.value, resolve_width(lu.width, ru.width))
        raise TypeError(f"multiplication expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_div(self, left, right):
        """Integer division (truncates toward zero).  Returns ExpectedValue."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            if ru.value == 0:
                return self._division_error()
            result = int(lu.value / ru.value) if lu.value * ru.value >= 0 else -int(abs(lu.value) / abs(ru.value))
            return ExpectedValue.ok(self._mk_int(result, resolve_width(lu.width, ru.width)))
        raise TypeError(f"division expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_mod(self, left, right):
        """Remainder (truncation toward zero): a % b = a - trunc(a/b)*b.  Returns ExpectedValue."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            if ru.value == 0:
                return self._division_error()
            quot = int(lu.value / ru.value) if lu.value * ru.value >= 0 else -int(abs(lu.value) / abs(ru.value))
            return ExpectedValue.ok(self._mk_int(lu.value - quot * ru.value, resolve_width(lu.width, ru.width)))
        raise TypeError(f"remainder expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_eq(self, left, right):
        """Equality comparison."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
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
        if isinstance(lu, StrValue) and isinstance(ru, StrValue):
            return mk_bool(lu.value == ru.value)
        if isinstance(lu, BoolValue) and isinstance(ru, BoolValue):
            return mk_bool(lu.value == ru.value)
        if isinstance(lu, TypeValue) and isinstance(ru, TypeValue):
            return mk_bool(lu.name == ru.name)
        if type(lu) != type(ru):
            return mk_bool(False)
        return mk_bool(False)

    def _op_neq(self, left, right):
        """Inequality comparison."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        eq = self._op_eq(left, right)
        return mk_bool(not eq.value)

    def _op_lt(self, left, right):
        """Less-than comparison."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_bool(lu.value < ru.value)
        raise TypeError(f"less-than expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_gt(self, left, right):
        """Greater-than comparison."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_bool(lu.value > ru.value)
        raise TypeError(f"greater-than expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_lte(self, left, right):
        """Less-than-or-equal comparison."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_bool(lu.value <= ru.value)
        raise TypeError(f"less-equal expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_gte(self, left, right):
        """Greater-than-or-equal comparison."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_bool(lu.value >= ru.value)
        raise TypeError(f"greater-equal expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_and(self, left, right):
        """Short-circuit boolean and."""
        lu = unwrap_optional(left)
        if not to_bool(lu):
            return mk_bool(False)
        ru = unwrap_optional(right)
        return mk_bool(to_bool(ru))

    def _op_or(self, left, right):
        """Short-circuit boolean or."""
        lu = unwrap_optional(left)
        if to_bool(lu):
            return mk_bool(True)
        ru = unwrap_optional(right)
        return mk_bool(to_bool(ru))

    def _op_lshift(self, left, right):
        """Left shift: int << int."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_int_wrap(lu.value << ru.value, resolve_width(lu.width, ru.width))
        raise TypeError(f"left-shift expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_rshift(self, left, right):
        """Logical right shift: int >> int.

        For typed unsigned integers, the value is already non-negative so
        Python's >> produces the correct logical shift.  mk_int wraps the
        result to the type's range.
        """
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            w = resolve_width(lu.width, ru.width)
            val = wrap_int(lu.value, lu.width)
            return mk_int_wrap(val >> ru.value, w)
        raise TypeError(f"right-shift expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_bitand(self, left, right):
        """Bitwise AND: int & int or flag_enum & flag_enum."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
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
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
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
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
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
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
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
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
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
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        return mk_bool(self._logic_bool(lu) and self._logic_bool(ru))

    def _op_logic_or(self, left, right):
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        return mk_bool(self._logic_bool(lu) or self._logic_bool(ru))

    def _op_logic_xor(self, left, right):
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        return mk_bool(self._logic_bool(lu) != self._logic_bool(ru))

    def _op_logic_nand(self, left, right):
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        return mk_bool(not (self._logic_bool(lu) and self._logic_bool(ru)))

    def _op_logic_nor(self, left, right):
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        return mk_bool(not (self._logic_bool(lu) or self._logic_bool(ru)))

    def _op_concat(self, left, right):
        """Concatenate arrays at the outermost dimension."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
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
            ArrayValue(list(la.elements) + list(ra.elements),
                       element_type=etype))

    def _mk_int(self, value: int, width: str) -> IntValue:
        if self._wrapping:
            return mk_int_wrap(value, width)
        return mk_int(value, width)

    def _division_error(self) -> ExpectedValue:
        """Create an ExpectedValue.err for division by zero using std.errors."""
        try:
            std_obj = self.env.lookup("std")
            if isinstance(std_obj, ObjectValue):
                errors_enum = getattr(std_obj.obj, "errors", None)
                if isinstance(errors_enum, EnumType):
                    return ExpectedValue.err(
                        EnumValue(errors_enum, errors_enum.members["division_by_zero"]))
        except Exception:
            pass
        return ExpectedValue.err(mk_str("division by zero"))

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
            return ObjectValue(ArrayValue([op_fn(l, r) for l, r in zip(la.elements, ra.elements)],
                                          element_type=etype))
        if la is not None:
            return ObjectValue(ArrayValue([op_fn(l, right) for l in la.elements],
                                          element_type=la.element_type))
        if ra is not None:
            return ObjectValue(ArrayValue([op_fn(left, r) for r in ra.elements],
                                          element_type=ra.element_type))
        return op_fn(left, right)

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
        if isinstance(node, IntLit):
            return mk_int(node.value, node.width)

        if isinstance(node, StrLit):
            return mk_str(node.text)

        if isinstance(node, BoolLit):
            return mk_bool(node.value)

        if isinstance(node, NoneLit):
            return none()

        if isinstance(node, VarRef):
            return self.env.lookup(node.name)

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
            eu = unwrap_optional(expected)
            au = unwrap_optional(actual)
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
            if node.op == "\N{DOUBLE PLUS}":
                return self._op_concat(left, right)
            return self._apply_binop(self._ops[node.op], left, right)

        if isinstance(node, UnaryOp):
            operand = self.eval_expr(node.operand)
            if node.op == "-":
                unwrapped = unwrap_optional(operand)
                if isinstance(unwrapped, IntValue):
                    return self._mk_int(-unwrapped.value, unwrapped.width)
                raise TypeError(f"negation expected int, got {type(unwrapped).__name__}")
            if node.op == "~":
                unwrapped = unwrap_optional(operand)
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

        if isinstance(node, OptSome):
            value = self.eval_expr(node.value)
            return some(value)

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
                    raise _ReturnSentinel(ExpectedValue.err(val.err_value))
                raise _ReturnSentinel(none())
            if isinstance(val, SomeValue):
                return val.value
            if isinstance(val, NoneValue):
                raise _ReturnSentinel(none())
            return val

        if isinstance(node, FuncCall):
            args = [self.eval_expr(a) for a in node.args]
            return self._call_func(node.name, args)

        if isinstance(node, MethodCall):
            obj = self.eval_expr(node.obj)
            args = [self.eval_expr(a) for a in node.args]
            return self._call_method(obj, node.method, args)

        if isinstance(node, GetAttr):
            obj = self.eval_expr(node.obj)
            unwrapped = unwrap_optional(obj)
            if isinstance(unwrapped, EnumType):
                if node.attr in unwrapped.members:
                    return EnumValue(unwrapped, unwrapped.members[node.attr])
                raise AttributeError(
                    f"enum '{unwrapped.name}' has no member '{node.attr}'")
            if isinstance(unwrapped, TupleValue):
                if node.attr == "sizeof":
                    return mk_int(len(unwrapped.elements))
            if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
                if node.attr == "sizeof":
                    return mk_int(unwrapped.obj.sizeof)
            if isinstance(unwrapped, ObjectValue):
                attr_val = getattr(unwrapped.obj, node.attr, None)
                if attr_val is not None:
                    if isinstance(attr_val, EnumType):
                        return attr_val
                    if callable(attr_val):
                        return BuiltinBoundMethod(unwrapped.obj, node.attr)
                    if isinstance(attr_val, int):
                        return mk_int(attr_val)
                    if isinstance(attr_val, str):
                        return mk_str(attr_val)
                    if isinstance(attr_val, bool):
                        return mk_bool(attr_val)
                    return ObjectValue(attr_val)
            elif isinstance(unwrapped, IntValue):
                # int.value attribute? No, just return the int itself.
                pass
            return obj

        # Array literal [expr, expr, ...].
        if isinstance(node, ArrayLit):
            elements = [self.eval_expr(e) for e in node.elements]
            return ObjectValue(ArrayValue(elements))

        # Subscript read: arr[idx] or tuple[idx].
        if isinstance(node, Subscript):
            arr_val = self.eval_expr(node.obj)
            unwrapped = unwrap_optional(arr_val)
            if isinstance(unwrapped, TupleValue):
                idx_val = self.eval_expr(node.index)
                iu = unwrap_optional(idx_val)
                if isinstance(iu, IntValue):
                    return unwrapped.get(iu.value)
            if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
                idx_val = self.eval_expr(node.index)
                iu = unwrap_optional(idx_val)
                if isinstance(iu, IntValue):
                    return unwrapped.obj.get(iu.value)

        # Slice read: arr[start…end] (inclusive).
        if isinstance(node, SliceAccess):
            arr_val = self.eval_expr(node.obj)
            unwrapped = unwrap_optional(arr_val)
            if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
                s = unwrap_optional(self.eval_expr(node.start))
                e = unwrap_optional(self.eval_expr(node.end))
                if isinstance(s, IntValue) and isinstance(e, IntValue):
                    elems = unwrapped.obj.elements[s.value:e.value + 1]
                    return ObjectValue(ArrayValue(list(elems),
                                                  element_type=unwrapped.obj.element_type))

        if isinstance(node, RangeExpr):
            s = unwrap_optional(self.eval_expr(node.start))
            e = unwrap_optional(self.eval_expr(node.end))
            if not isinstance(s, IntValue) or not isinstance(e, IntValue):
                raise TypeError("range bounds must be integers")
            step = None
            if node.step is not None:
                st = unwrap_optional(self.eval_expr(node.step))
                if not isinstance(st, IntValue):
                    raise TypeError("range step must be an integer")
                step = st.value
            return RangeValue(s.value, e.value, step)

        if isinstance(node, EnumerateExpr):
            raise TypeError("@enumerate can only be used inside foreach")

        if isinstance(node, TypeOfExpr):
            val = self.eval_expr(node.expr)
            return TypeValue(self._value_type_name(val))

        if isinstance(node, SizeOfExpr):
            val = self.eval_expr(node.expr)
            unwrapped = unwrap_optional(val)
            if isinstance(unwrapped, TupleValue):
                return mk_int(len(unwrapped.elements))
            if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
                return mk_int(unwrapped.obj.sizeof)
            if isinstance(unwrapped, StrValue):
                return mk_int(len(unwrapped.value))
            raise TypeError(
                f"@sizeof: expected array, tuple, or string, got {type(unwrapped).__name__}")

        if isinstance(node, ResultOfExpr):
            try:
                func = self.env.lookup(node.name)
            except KeyError:
                raise TypeError(f"@resultof: unknown function '{node.name}'")
            if isinstance(func, FuncValue):
                return TypeValue(func.ret_type or "\N{EMPTY SET}")
            if isinstance(func, BuiltinFunc):
                return TypeValue("builtin")
            raise TypeError(f"@resultof: '{node.name}' is not a function")

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
            size_val = self.eval_expr(node.size_expr)
            sz = unwrap_optional(size_val)
            if isinstance(sz, IntValue):
                init_val = self.eval_expr(node.init_expr) if node.init_expr is not None else mk_int(0)
                if etype and isinstance(init_val, IntValue):
                    init_val = mk_int(init_val.value, etype)
                return ObjectValue(ArrayValue([init_val] * sz.value, element_type=etype))

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
        """Evaluate a single statement.

        Returns:
            The last computed value, or a _ReturnSentinel for return statements.
        """
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
            rhs = self.eval_expr(rhs_ast)
            if isinstance(target_ast, SliceAccess):
                # arr[s…e] ← rhs_array — copy elements into slice.
                arr_val = self.eval_expr(target_ast.obj)
                au = unwrap_optional(arr_val)
                if isinstance(au, ObjectValue) and isinstance(au.obj, ArrayValue):
                    s = unwrap_optional(self.eval_expr(target_ast.start))
                    e = unwrap_optional(self.eval_expr(target_ast.end))
                    rhs_arr = self._as_array(rhs)
                    if isinstance(s, IntValue) and isinstance(e, IntValue) and rhs_arr is not None:
                        for i, val in enumerate(rhs_arr.elements):
                            au.obj.set(s.value + i, val)
            elif isinstance(target_ast, Subscript):
                # arr[i] ← value — mutate array element.
                arr_val = self.eval_expr(target_ast.obj)
                au = unwrap_optional(arr_val)
                if isinstance(au, ObjectValue) and isinstance(au.obj, ArrayValue):
                    idx_val = self.eval_expr(target_ast.index)
                    iu = unwrap_optional(idx_val)
                    if isinstance(iu, IntValue):
                        au.obj.set(iu.value, rhs)
            elif isinstance(target_ast, VarRef):
                if target_ast.name in self._frozen_vars:
                    kind = self._frozen_vars[target_ast.name]
                    raise TypeError(
                        f"cannot assign to {kind} variable '{target_ast.name}'")
                self.env.define(target_ast.name, rhs)
            return none()

        if isinstance(stmt, VarDef):
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
                value = coerce_to_type(value, stmt.type_annotation)
            self.env.define(stmt.name, value)
            if stmt.is_const:
                self._frozen_vars[stmt.name] = "const"
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

    def _eval_while(self, node: WhileStmt):
        """Evaluate a while loop. Repeatedly check condition and execute body."""
        while to_bool(self.eval_expr(node.cond)):
            self.eval_stmts(node.body)
        return none()

    def _eval_foreach(self, node: ForEachStmt):
        """Evaluate a foreach loop over ranges or containers."""
        sequences: list[list[Value]] = []
        for expr in node.iterables:
            if isinstance(expr, EnumerateExpr):
                inner = self._resolve_iterable(expr.expr, node.is_comptime)
                sequences.append([
                    TupleValue([mk_int(i), v]) for i, v in enumerate(inner)
                ])
            elif isinstance(expr, RangeExpr):
                s = unwrap_optional(self.eval_expr(expr.start))
                e = unwrap_optional(self.eval_expr(expr.end))
                if not isinstance(s, IntValue) or not isinstance(e, IntValue):
                    raise TypeError("range bounds must be integers")
                sv, ev = s.value, e.value
                if expr.step is not None:
                    st = unwrap_optional(self.eval_expr(expr.step))
                    if not isinstance(st, IntValue):
                        raise TypeError("range step must be an integer")
                    stv = st.value
                    if stv == 0:
                        raise TypeError("range step must not be zero")
                    if stv > 0:
                        sequences.append([mk_int(i) for i in range(sv, ev + 1, stv)])
                    else:
                        sequences.append([mk_int(i) for i in range(sv, ev - 1, stv)])
                elif sv <= ev:
                    sequences.append([mk_int(i) for i in range(sv, ev + 1)])
                else:
                    sequences.append([mk_int(i) for i in range(sv, ev - 1, -1)])
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
        for name in var_names:
            self._frozen_vars[name] = "foreach"
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
                        if var_type is not None:
                            val = coerce_to_type(val, var_type)
                        self.env.define(var_name, val)
                self.eval_stmts(node.body)
        finally:
            for name in var_names:
                self._frozen_vars.pop(name, None)
        return none()

    def _resolve_iterable(self, expr, is_comptime: bool = False) -> list[Value]:
        """Resolve an expression to a list of values for foreach iteration."""
        val = unwrap_optional(self.eval_expr(expr))
        if isinstance(val, RangeValue):
            return [mk_int(i) for i in val.to_list()]
        if isinstance(val, ObjectValue) and isinstance(val.obj, ArrayValue):
            return list(val.obj.elements)
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
        etype: str | None = None
        if isinstance(du, IntValue):
            source = [du]
        elif isinstance(du, ObjectValue) and isinstance(du.obj, ArrayValue):
            source = list(du.obj.elements)
            etype = du.obj.element_type
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
            elements = list(cu.obj.elements)
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
        if isinstance(val, (BuiltinFunc, EnumType)):
            return True
        if isinstance(val, FuncValue) and not val.is_replaceable:
            return True
        if isinstance(val, ObjectValue) and not isinstance(val.obj, ArrayValue):
            return True
        return False

    @staticmethod
    def _value_type_name(val: Value) -> str:
        """Return the type name string for a runtime value."""
        u = unwrap_optional(val)
        if isinstance(u, IntValue):
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
            return self._wrap_optional_return(result, lam.ret_type)
        except _ReturnSentinel as e:
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
                    return ObjectValue(result)
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
                return ObjectValue(result)
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

        if has_generics:
            generic_map: dict[str, str] = {}
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
            if param_type is not None:
                arg_value = coerce_arg(arg_value, param_type, func.name, param_name)
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
        try:
            self.env = call_env
            self._current_ret_type = resolved_ret_type
            result = self.eval_stmts(func.body)
            return self._wrap_optional_return(result, resolved_ret_type)
        except _ReturnSentinel as e:
            return self._wrap_optional_return(e.value, resolved_ret_type)
        except _PropagatedError as pe:
            raise pe.original from pe
        finally:
            self.env = old_env
            self._current_ret_type = old_ret_type

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
