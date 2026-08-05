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

from interp.ast import (
    IntLit, StrLit, BoolLit, NoneLit, VarRef, BinOp, UnaryOp,
    IfStmt, WhileStmt, ReturnStmt, FuncDef, VarDef, ExprStmt,
    FuncCall, MethodCall, OptSome, GetAttr,
    ArrayLit, Subscript, SliceAccess, ArrayAlloc, TryUnwrap,
)
from interp.value import (
    Value, IntValue, StrValue, BoolValue, NoneValue, SomeValue,
    FuncValue, BuiltinFunc, ObjectValue, BuiltinBoundMethod, ArrayValue,
    mk_int, mk_str, mk_bool, none, some, is_none, is_some,
    resolve_width, wrap_int, coerce_to_type, coerce_arg, _TYPE_BITS,
)
from interp.env import Env
from interp.std import std, DirFD, FileStream, Bytes, MmapAllocator


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def unwrap_optional(value):
    """Unwrap an optional value for comparison/conversion.

    If value is SomeValue, returns the inner value.
    If value is NoneValue, returns None (Python).
    Otherwise, returns the value itself (for non-optional values).
    """
    if isinstance(value, SomeValue):
        return value.value
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
            return "none"
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
        }

    # ------------------------------------------------------------------
    # Binary operators
    # ------------------------------------------------------------------

    def _op_add(self, left, right):
        """Addition: integers and strings (concatenation)."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_int(lu.value + ru.value, resolve_width(lu.width, ru.width))
        if isinstance(lu, StrValue) and isinstance(ru, StrValue):
            return mk_str(lu.value + ru.value)
        raise TypeError(f"addition expected int+int or str+str, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_sub(self, left, right):
        """Subtraction."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_int(lu.value - ru.value, resolve_width(lu.width, ru.width))
        raise TypeError(f"subtraction expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_mul(self, left, right):
        """Multiplication."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_int(lu.value * ru.value, resolve_width(lu.width, ru.width))
        raise TypeError(f"multiplication expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_div(self, left, right):
        """Integer division (truncates toward zero)."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            if ru.value == 0:
                raise ZeroDivisionError("division by zero")
            result = int(lu.value / ru.value) if lu.value * ru.value >= 0 else -int(abs(lu.value) / abs(ru.value))
            return mk_int(result, resolve_width(lu.width, ru.width))
        raise TypeError(f"division expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_mod(self, left, right):
        """Remainder (truncation toward zero): a % b = a - trunc(a/b)*b."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            if ru.value == 0:
                raise ZeroDivisionError("remainder by zero")
            quot = int(lu.value / ru.value) if lu.value * ru.value >= 0 else -int(abs(lu.value) / abs(ru.value))
            return mk_int(lu.value - quot * ru.value, resolve_width(lu.width, ru.width))
        raise TypeError(f"remainder expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_eq(self, left, right):
        """Equality comparison."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_bool(lu.value == ru.value)
        if isinstance(lu, StrValue) and isinstance(ru, StrValue):
            return mk_bool(lu.value == ru.value)
        if isinstance(lu, BoolValue) and isinstance(ru, BoolValue):
            return mk_bool(lu.value == ru.value)
        # Cross-type: only None == None is true.
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
            return mk_int(lu.value << ru.value, resolve_width(lu.width, ru.width))
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
            return mk_int(val >> ru.value, w)
        raise TypeError(f"right-shift expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_bitand(self, left, right):
        """Bitwise AND: int & int."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_int(lu.value & ru.value, resolve_width(lu.width, ru.width))
        raise TypeError(f"bitwise-and expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_bitxor(self, left, right):
        """Bitwise XOR: int ^ int."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_int(lu.value ^ ru.value, resolve_width(lu.width, ru.width))
        raise TypeError(f"bitwise-xor expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_bitor(self, left, right):
        """Bitwise OR: int | int."""
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_int(lu.value | ru.value, resolve_width(lu.width, ru.width))
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
            return mk_int(result, w)
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
            return mk_int(result, w)
        raise TypeError(f"rotate-right expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

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

        if isinstance(node, BinOp):
            if node.op == "??":
                left = self.eval_expr(node.left)
                if isinstance(left, SomeValue):
                    return left.value
                if isinstance(left, NoneValue):
                    return self.eval_expr(node.right)
                return left
            left = self.eval_expr(node.left)
            right = self.eval_expr(node.right)
            return self._apply_binop(self._ops[node.op], left, right)

        if isinstance(node, UnaryOp):
            operand = self.eval_expr(node.operand)
            if node.op == "-":
                unwrapped = unwrap_optional(operand)
                if isinstance(unwrapped, IntValue):
                    return mk_int(-unwrapped.value, unwrapped.width)
                raise TypeError(f"negation expected int, got {type(unwrapped).__name__}")
            if node.op == "~":
                unwrapped = unwrap_optional(operand)
                if isinstance(unwrapped, IntValue):
                    return mk_int(~unwrapped.value, unwrapped.width)
                raise TypeError(f"bitwise-not expected int, got {type(unwrapped).__name__}")
            if node.op == "not":
                return mk_bool(not to_bool(operand))

        if isinstance(node, OptSome):
            value = self.eval_expr(node.value)
            return some(value)

        if isinstance(node, TryUnwrap):
            if not self._current_ret_type or not self._current_ret_type.startswith("?"):
                raise TypeError(
                    "? operator requires enclosing function to have optional return type")
            val = self.eval_expr(node.expr)
            if isinstance(val, SomeValue):
                return val.value
            if isinstance(val, NoneValue):
                raise _ReturnSentinel(none())
            raise TypeError("? operator requires optional value")

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
            if isinstance(unwrapped, ObjectValue):
                attr_val = getattr(unwrapped.obj, node.attr, None)
                if attr_val is not None:
                    if callable(attr_val):
                        # Return a bound method wrapper.
                        return BuiltinBoundMethod(unwrapped.obj, node.attr)
                    # Convert plain Python values to Value types.
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

        # Subscript read: arr[idx].
        if isinstance(node, Subscript):
            arr_val = self.eval_expr(node.obj)
            unwrapped = unwrap_optional(arr_val)
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

        # Array allocation: new type[size] or var name : type[size] = init.
        if isinstance(node, ArrayAlloc):
            size_val = self.eval_expr(node.size_expr)
            sz = unwrap_optional(size_val)
            if isinstance(sz, IntValue):
                init_val = self.eval_expr(node.init_expr) if node.init_expr is not None else mk_int(0)
                etype = node.element_type
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
                # name ← value — shadow in current scope.
                self.env.define(target_ast.name, rhs)
            return none()

        if isinstance(stmt, VarDef):
            value = self.eval_expr(stmt.init_expr)
            if stmt.type_annotation is not None:
                value = coerce_to_type(value, stmt.type_annotation)
            self.env.define(stmt.name, value)
            return none()

        if isinstance(stmt, ExprStmt):
            return self.eval_expr(stmt.expr)

        if isinstance(stmt, IfStmt):
            return self._eval_if(stmt)

        if isinstance(stmt, WhileStmt):
            return self._eval_while(stmt)

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
        """Dispatch a call to either user-defined or builtin function."""
        if isinstance(func, FuncValue):
            return self._call_user_func(func, args)
        if isinstance(func, BuiltinFunc):
            expected = func.arity
            if expected != -1 and len(args) != expected:
                raise TypeError(
                    f"{func.name} expects {expected} arguments, got {len(args)}")
            return func.func(args)
        if isinstance(func, BuiltinBoundMethod):
            return func(*args)
        raise TypeError(f"cannot call {type(func).__name__}")

    def _call_user_func(self, func: FuncValue, args):
        """Call a user-defined function with proper scoping."""
        if func.name in self._test_hooks:
            pending = self._test_hooks.pop(func.name)
            for test_fv in pending:
                if test_fv.name not in self._tests_run:
                    self._tests_run.add(test_fv.name)
                    self._call_user_func(test_fv, [])
                    import sys
                    print(f"test {test_fv.name} ... ok", file=sys.stderr)

        if len(args) != len(func.params):
            raise TypeError(
                f"{func.name} expects {len(func.params)} arguments, got {len(args)}")

        # Create new environment frame for this call.
        call_env = self.env.copy_for_call()

        for (param_name, param_type), arg_value in zip(func.params, args):
            if param_type is not None:
                arg_value = coerce_arg(arg_value, param_type, func.name, param_name)
            call_env.define(param_name, arg_value)

        # Execute function body with the call's environment as our context.
        old_env = self.env
        old_ret_type = self._current_ret_type
        try:
            self.env = call_env
            self._current_ret_type = func.ret_type
            result = self.eval_stmts(func.body)
            return self._wrap_optional_return(result, func.ret_type)
        except _ReturnSentinel as e:
            return self._wrap_optional_return(e.value, func.ret_type)
        finally:
            self.env = old_env
            self._current_ret_type = old_ret_type

    def _wrap_optional_return(self, result: Value, ret_type: str | None) -> Value:
        """Wrap return value in SomeValue for functions with optional return types."""
        if not ret_type or not ret_type.startswith("?"):
            return result
        if isinstance(result, NoneValue):
            return result
        base_type = ret_type[1:]
        if isinstance(result, IntValue) and base_type not in ("int", ""):
            result = mk_int(result.value, base_type)
        return some(result)


class _ReturnSentinel(BaseException):
    """Internal sentinel for non-local return from functions.

    Carries the return value and is caught by eval_stmts to produce
    a clean return path without requiring exceptions in normal flow.
    """

    def __init__(self, value: Value):
        self.value = value
