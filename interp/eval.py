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

import math
import re
import sys as _sys
import time as _time

# ---------------------------------------------------------------------------
# Forward-progress watchdog.
#
# Long runs -- the compiler compiling itself under this interpreter --
# need two assurances: that a hang produces a diagnostic instead of
# silence, and that a slow run can be seen to be moving.  Armed from
# the command line (--timeout, --heartbeat) or the NGPLI_TIMEOUT /
# NGPLI_HEARTBEAT environment variables; checked at statement
# boundaries, with the clock read only every few thousand statements
# so an unarmed or quiet watchdog costs almost nothing.
# ---------------------------------------------------------------------------

_WATCHDOG_CHECK_EVERY = 4096
_watchdog_armed: bool = False
_watchdog_deadline: float | None = None
_watchdog_started: float = 0.0
_watchdog_beat_every: float = 0.0
_watchdog_next_beat: float = 0.0
_watchdog_steps: int = 0
_watchdog_countdown: int = _WATCHDOG_CHECK_EVERY


def arm_watchdog(timeout: float | None, heartbeat: float | None) -> None:
    """Arm the forward-progress watchdog for this process.

    timeout: seconds after which the run is stopped with a backtrace,
        or None for no limit.
    heartbeat: seconds between progress reports on stderr, or None for
        no reports.
    """
    global _watchdog_armed, _watchdog_deadline, _watchdog_started
    global _watchdog_beat_every, _watchdog_next_beat
    now = _time.monotonic()
    _watchdog_started = now
    if timeout is not None and timeout > 0:
        _watchdog_deadline = now + timeout
        _watchdog_armed = True
    if heartbeat is not None and heartbeat > 0:
        _watchdog_beat_every = heartbeat
        _watchdog_next_beat = now + heartbeat
        _watchdog_armed = True


class NoForwardProgress(RuntimeError):
    """The armed time limit passed before the program finished."""


# Progress is also recorded per function: every completed call to a
# user-defined function counts, and the most recently finished one is
# named in the heartbeat, so a run that is moving shows *what* it is
# moving through.  With --fn-stats the record is complete: calls and
# cumulative time per function, printed when the process ends (and on
# a timeout), which is how a super-linear cost is found.
_fn_calls_done: int = 0
_fn_last_name: str = ""
_fn_stats_on: bool = False
_fn_stats: dict = {}


def enable_fn_stats() -> None:
    global _fn_stats_on
    _fn_stats_on = True
    import atexit
    atexit.register(report_fn_stats)


def report_fn_stats(limit: int = 30) -> None:
    """Print the per-function record to stderr, the costliest first."""
    if not _fn_stats:
        return
    rows = sorted(_fn_stats.items(), key=lambda kv: -kv[1][1])[:limit]
    width = max(len(name) for name, _ in rows)
    print(f"interp: function record ({_fn_calls_done:,} calls finished):",
          file=_sys.stderr)
    for name, (count, cum) in rows:
        print(f"interp:   {name:<{width}}  {count:>10,} calls  "
              f"{cum:>9.2f}s cumulative", file=_sys.stderr, flush=True)


from interp.ast import (
    IntLit, FloatLit, StrLit, CharLit, BoolLit, NoneLit, VarRef, BinOp, UnaryOp,
    IfStmt, IfExpr, WhileStmt, ReturnStmt, FuncDef, VarDef, DestructureDef,
    ExprStmt,
    FuncCall, MethodCall, OptSome, GetAttr,
    ArrayLit, Subscript, SliceAccess, MultiSlice, ArrayAlloc, TryUnwrap,
    DropUnitExpr,
    LimitExpr,
    RangeExpr, ForEachStmt, ExpectStmt, WrapExpr, LambdaExpr, SumTypeDef,
    ReshapeExpr, MapExpr, TupleLit, CatchStmt, EnumerateExpr,
    HashLit, SetLit, EmptyCollectionLit, BreakStmt, ContinueStmt,
    Quote, Splice, Reflect,
    StaticAssert, StaticAssertEq, TypeOfExpr, ResultOfExpr, SizeOfExpr, FoldExpr,
    OperatorRef,
    UnitExpr, UnitOfExpr, UnitRefExpr, RefExpr, BorrowExpr, TypeDef,
    MatchStmt, ExpErr,
    StructLit,
)
from interp.value import (
    Value, IntValue, FloatValue, StrValue, BoolValue, NoneValue, SomeValue, ExpectedValue,
    FuncValue, LambdaValue, BuiltinFunc, ObjectValue, BuiltinBoundMethod,
    ArrayValue, HashValue, SetValue, hash_key,
    TupleValue, EnumType, EnumValue, RangeValue, TypeValue, UnitOfValue,
    StructType, StructInstance,
    mk_int, mk_int_wrap, mk_str, mk_bool, mk_float, none, some, is_none, is_some,
    resolve_width, resolve_float_width, wrap_int, coerce_to_type, coerce_arg,
    _TYPE_BITS, FLOAT_TYPES, FAST_TYPES,
    _split_optional_type, _parse_array_type, MAX_TENSOR_RANK, array_shape,
    int_limits, float_limits, resolve_type_alias,
    format_shape, _array_type_name, array_type_mismatch,
    is_generic_type, runtime_type_of, is_type_name, _is_unsigned, validate_type,
    declared_rank, value_rank, threaded_array,
    check_bootstrap_argument, check_bootstrap_type, check_binding_settles,
    check_bootstrap_binding,
    UNTYPED, is_unwidthed, settle_untyped, apply_unit, convert_unit_value,
    _scalar_kind_mismatch,
    CharValue, check_code_point, TRUE_VALUE, FALSE_VALUE,
    UnitValue, RefValue, Reference, ElementRef, Iterator, ArrayIterator,
    deep_copy_value, register_type_alias, DISCARD_NAME,
    register_sum_type, sum_type_alternatives, sum_type_admits,
    SyntaxValue,
)
from interp.env import Env, Decl
from interp.std import (std, DirFD, FileStream, Bytes, MmapAllocator,
                       resolve_abort_signal)
from interp.errors import (attach_backtrace, diagnostic_level, coded,
                          strip_position_prefix, ContractError,
                          contract_semantic, report_runtime_diagnostic,
                          ProgramAbort)


# What a piece of the program says it is.  The parse tree's own class
# names are an implementation detail; these are what a program reads.
_SYNTAX_KINDS = {
    "IntLit": "number", "FloatLit": "number", "StrLit": "string",
    "CharLit": "character", "BoolLit": "truth", "NoneLit": "nothing",
    "VarRef": "name", "GetAttr": "name", "BinOp": "operator",
    "UnaryOp": "operator", "FuncCall": "call", "MethodCall": "call",
    "ArrayLit": "array", "TupleLit": "tuple", "LambdaExpr": "function",
}


# What a node holds that says where it was written rather than what it
# is.  Two pieces of the program written alike are alike whatever these
# say.
_SYNTAX_POSITION_FIELDS = frozenset({"pos", "label_pos", "field_positions"})


def _tree_fields(node) -> tuple:
    """The names of what a node holds, however the node stores them."""
    if hasattr(node, "__dict__"):
        names = tuple(vars(node))
    else:
        names = tuple(getattr(type(node), "__slots__", ()))
    return tuple(n for n in names if n not in _SYNTAX_POSITION_FIELDS)


def _alike_trees(a, b) -> bool:
    """Whether two pieces of parse tree say the same thing."""
    a_is_node = type(a).__module__ == "interp.ast"
    b_is_node = type(b).__module__ == "interp.ast"
    if a_is_node or b_is_node:
        if not (a_is_node and b_is_node) or type(a) is not type(b):
            return False
        return all(_alike_trees(getattr(a, f, None), getattr(b, f, None))
                   for f in _tree_fields(a))
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        return (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))
                and len(a) == len(b)
                and all(_alike_trees(x, y) for x, y in zip(a, b)))
    return a == b


# What a piece of the program that applies nothing is made of.  Every
# piece has a head, so an atom answers the most particular name the
# language has for what it is -- which for a written-down number is the
# type the literal states.
_HEAD_OF_KIND = {
    "StrLit": "str", "CharLit": "char", "BoolLit": "bool",
    "ArrayLit": "array", "TupleLit": "tuple", "HashLit": "dict",
    "SetLit": "set", "EmptyCollectionLit": "collection",
    "LambdaExpr": "fn", "RangeExpr": "range",
    # A name's type is not knowable here: a macro runs before anything
    # is checked, so what a name answers is that it is a name.
    "VarRef": "name", "GetAttr": "name",
}


def _head_of(node):
    """What a piece of the program is made by.

    Every piece has one.  For something that applies something else,
    the head is what it applies: an operator is what its expression
    applies exactly as a function is what a call applies, so `a × b`
    and `f(a, b)` answer the same kind of thing and are taken apart the
    same way.  For something that applies nothing, the head is the most
    particular name the language has for what it is -- for a number
    written down, the type its literal states.

    Wolfram answers Head the same way, and for the same reason: a
    question every expression answers is worth more than one that has
    to be asked whether it has an answer.
    """
    from interp.ast import (BinOp as _BinOp, UnaryOp as _UnaryOp,
                            FuncCall as _FuncCall, MethodCall as _MethodCall,
                            OperatorRef as _OperatorRef, VarRef as _VarRef,
                            GetAttr as _GetAttr, IntLit as _IntLit,
                            FloatLit as _FloatLit, NoneLit as _NoneLit)

    if isinstance(node, (_BinOp, _UnaryOp)):
        return _OperatorRef(node.op)
    if isinstance(node, _FuncCall):
        return _VarRef(node.name)
    if isinstance(node, _MethodCall):
        return _GetAttr(node.obj, node.method)
    if isinstance(node, (_IntLit, _FloatLit)):
        # The width the literal states, which is what a program would
        # write the type as.
        return _VarRef(node.width)
    if isinstance(node, _NoneLit):
        return _VarRef("\N{EMPTY SET}")
    named = _HEAD_OF_KIND.get(type(node).__name__)
    return _VarRef(named if named is not None else "expression")


def _arguments_of(node) -> list:
    """What a piece of the program applies its head to.

    Empty where it applies nothing, so a caller that asked for the head
    first and got nothing has nothing here either.
    """
    from interp.ast import (BinOp as _BinOp, UnaryOp as _UnaryOp,
                            FuncCall as _FuncCall, MethodCall as _MethodCall)

    if isinstance(node, _BinOp):
        return [node.left, node.right]
    if isinstance(node, _UnaryOp):
        return [node.operand]
    if isinstance(node, (_FuncCall, _MethodCall)):
        return list(node.args)
    return []


# An empty array disagrees with no unit, so it stands in for whatever
# one is asked of it.
_EMPTY_MEASURE = object()


def _is_keyed_container(value) -> bool:
    """Whether a value is a dictionary or a set."""
    return (isinstance(value, ObjectValue)
            and isinstance(value.obj, (HashValue, SetValue)))


def _flatten_names(name):
    """Every name a loop variable binds, a pattern holding several."""
    if isinstance(name, tuple):
        out = []
        for one in name:
            out.extend(_flatten_names(one))
        return out
    return [name]


def _sizeof_is_gone(attr: str) -> str:
    """Say where the two questions .sizeof used to answer went.

    It answered how many things were in a container and how much memory
    a struct took, which are not the same question and now are not the
    same word: # counts, @sizeof measures.
    """
    return (f".{attr} is not a member; # is how many things are in a "
            f"container -- an array, a string, a tuple -- and @sizeof is "
            f"how much memory something takes")


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

def _element_kind(value) -> str:
    """How an element of an array literal reads in a diagnostic."""
    inner = value.inner if isinstance(value, UnitValue) else value
    if isinstance(inner, IntValue):
        return "an untyped number" if is_unwidthed(inner.width) else inner.width
    if isinstance(inner, FloatValue):
        return "an untyped number" if inner.width == "float" else inner.width
    if isinstance(inner, CharValue):
        return "a character"
    if isinstance(inner, StrValue):
        return "a string"
    if isinstance(inner, BoolValue):
        return "a boolean"
    if isinstance(inner, ObjectValue) and isinstance(inner.obj, ArrayValue):
        return "an array"
    return runtime_type_of(inner)


def _literal_element_type(elements):
    """What the elements of an array literal settle on between them.

    An array holds one type of value, so the elements have to agree
    before there is anything for the array to be an array of.  An
    element that states a width says what the array is made of and the
    ones that state none take it, as they would meeting the same width
    anywhere else; where none of them states one there is nothing to
    settle on and a binding has to say.

    Two that disagree are refused here rather than left for a type to
    sort out, since without a type nothing would ever sort them out and
    the array would hold whatever it was handed.
    """
    width = None
    said_by = 0
    kind = None
    kind_by = 0
    unit = None
    unit_by = 0
    rows: list[tuple[int, list | None]] = []
    for index, element in enumerate(elements):
        if isinstance(element, UnitValue):
            # A unit settles the way a width does: one element states
            # it and the bare ones take it, wherever in the literal it
            # is written.
            if unit is None:
                unit, unit_by = element.unit, index
            elif not unit.same_dimension(element.unit):
                raise coded(2320, TypeError(
                    f"an array holds one unit, but element {unit_by} is "
                    f"{unit.display_name} and element {index} is "
                    f"{element.unit.display_name}"))
        inner = element.inner if isinstance(element, UnitValue) else element
        if isinstance(inner, (NoneValue, SomeValue)):
            # An array holds values; ∅ is the absence of one and ∃ its
            # box, and neither is an element type an array can be of.
            raise coded(2741, TypeError(
                f"an array element is a value, but element {index} is "
                + ("∅, the absence of one" if isinstance(inner, NoneValue)
                   else "boxed; take ∃ apart before storing")))
        if isinstance(inner, (IntValue, FloatValue)):
            found_kind = "number"
        elif isinstance(inner, CharValue):
            found_kind = "char"
        elif isinstance(inner, StrValue):
            found_kind = "str"
        elif isinstance(inner, BoolValue):
            found_kind = "bool"
        elif isinstance(inner, ObjectValue) \
                and isinstance(inner.obj, ArrayValue):
            found_kind = "array"
        else:
            # A struct, an enum or a tuple: what those hold in common
            # is a question their own types answer, and a binding is
            # where they are measured.
            return None, None
        if kind is None:
            kind, kind_by = found_kind, index
        elif kind != found_kind:
            raise coded(2743, TypeError(
                f"an array holds one type of value, but element {kind_by} is "
                f"{_element_kind(elements[kind_by])} and element {index} is "
                f"{_element_kind(element)}"))
        if isinstance(inner, ObjectValue):
            # A row is settled by what is in it, and by what is in
            # every other row: one number saying what it is says it for
            # all of them, however deep in the literal it was written.
            row = inner.obj
            row_elem, row_unit = _literal_element_type(
                [row.get(i) for i in range(row.sizeof)])
            if row_unit is not None:
                if unit is None:
                    unit, unit_by = row_unit, index
                elif not unit.same_dimension(row_unit):
                    raise TypeError(
                        f"an array holds one unit, but element {unit_by} is "
                        f"{unit.display_name} and element {index} is "
                        f"{row_unit.display_name}")
            # Only what is at the bottom is compared between rows: how
            # long each row is belongs to the shape, which a type says
            # and which rows are allowed to disagree about here.
            if row_elem is None:
                rows.append((row.sizeof, None))
                continue
            parsed = _parse_array_type(row_elem)
            base, inner_dims = parsed if parsed else (row_elem, [])
            rows.append((row.sizeof, inner_dims))
            found = base
        elif isinstance(inner, IntValue):
            if is_unwidthed(inner.width):
                continue
            found = inner.width
        elif isinstance(inner, FloatValue):
            if inner.width == "float":
                continue
            found = inner.width
        elif isinstance(inner, CharValue):
            found = "char"
        elif isinstance(inner, StrValue):
            found = "str"
        else:
            found = "bool"
        if width is not None and width != found:
            raise coded(2744, TypeError(
                f"an array holds one type of value, but element {said_by} is "
                f"{width} and element {index} is {found}"))
        width, said_by = found, index
    if kind == "array" and width is not None:
        # What one element of this array is: a row of what the bottom
        # settled on, as long as the rows agree on it.  Rows of
        # different lengths leave the extent open, raggedness being a
        # question about the shape rather than about the type.
        lengths = {length for length, _ in rows}
        shapes = {tuple(dims) for _, dims in rows if dims is not None}
        if len(shapes) > 1:
            return None, unit
        tail = list(shapes.pop()) if shapes else []
        first = lengths.pop() if len(lengths) == 1 else None
        return _array_type_name(width, [first, *tail]), unit
    return width, unit


def _parameter_names(params) -> set[str]:
    """Every name a parameter list binds, destructured ones included."""
    names: set[str] = set()
    for pname, _ptype in params:
        if isinstance(pname, tuple):
            names |= _parameter_names([(n, None) for n in pname])
        else:
            names.add(pname)
    return names


def _joins_as_text(value) -> bool:
    """Whether ⧺ reads this operand as text.

    A string and a character, and nothing else.  A number is not text,
    and an array is the other thing ⧺ joins.
    """
    return isinstance(value, (StrValue, CharValue))


def _names_display(names) -> str:
    """How a destructured parameter's names read in a diagnostic."""
    return "(" + ", ".join(_names_display(n) if isinstance(n, tuple) else n
                           for n in names) + ")"


def _collect_refs_from_stmts(stmts) -> set[str]:
    """Collect all variable/function references from a list of statements."""
    refs: set[str] = set()
    for stmt in stmts:
        if isinstance(stmt, VarDef):
            refs |= _collect_refs(stmt.init_expr)
        elif isinstance(stmt, DestructureDef):
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
        inner -= _parameter_names(node.params)
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


# Settings of the runtime that a program may write to.  Everything
# else std holds is something it provides rather than something it is
# told.
_STD_SETTINGS = frozenset({"comparison_tolerance"})


def _is_const_expr(node) -> bool:
    """Check whether an AST node is a compile-time constant expression."""
    if isinstance(node, (IntLit, FloatLit, StrLit, CharLit, BoolLit, NoneLit)):
        return True
    if isinstance(node, BinOp):
        return _is_const_expr(node.left) and _is_const_expr(node.right)
    if isinstance(node, UnaryOp):
        return _is_const_expr(node.operand)
    # A choice between two constants, made by a constant, is one too --
    # which is what lets @typeof answer for one.
    if isinstance(node, IfExpr):
        return (_is_const_expr(node.cond) and _is_const_expr(node.then_expr)
                and _is_const_expr(node.else_expr))
    if isinstance(node, ArrayLit):
        return all(_is_const_expr(e) for e in node.elements)
    if isinstance(node, TupleLit):
        return all(_is_const_expr(e) for e in node.elements)
    if isinstance(node, (TypeOfExpr, ResultOfExpr, SizeOfExpr, UnitOfExpr,
                         UnitRefExpr, LimitExpr)):
        return True
    # A type name stands for its type, which is as constant as a literal.
    if isinstance(node, VarRef) and is_type_name(node.name):
        return True
    if isinstance(node, Subscript) and isinstance(node.obj, VarRef) \
            and is_type_name(node.obj.name):
        # And so does one with brackets after it, which is an array
        # type rather than a subscript of anything.
        return all(index is None or isinstance(index, IntLit)
                   for index in node.indices)
    if isinstance(node, UnitExpr):
        return _is_const_expr(node.expr)
    if isinstance(node, GetAttr):
        # std.implementation.<member> says which implementation runs
        # the program, which is settled before anything does.
        if (isinstance(node.obj, GetAttr)
                and node.obj.attr == "implementation"
                and isinstance(node.obj.obj, VarRef)
                and node.obj.obj.name == "std"):
            return True
        # A member that answers about the value rather than holding
        # part of it: how many elements it has, and how it is laid out.
        return (node.attr in _CONST_ATTRIBUTES
                and not isinstance(node.obj, StructLit)
                and _is_const_expr(node.obj))
    if isinstance(node, MethodCall):
        # A member function is constant where it says the same thing
        # about the same value every time it is asked.  The conversions
        # between a number, a character, and a string are those: each
        # is total on what it accepts and reads nothing else.  A struct
        # literal is excluded, since a method of one is a function the
        # program wrote and may do anything.
        return (node.method in _CONST_METHODS
                and not isinstance(node.obj, StructLit)
                and _is_const_expr(node.obj)
                and all(_is_const_expr(a) for a in node.args))
    return False


# Members a constant value answers constantly.
_CONST_METHODS = frozenset({"ord", "chr", "str", "chars"})
_CONST_ATTRIBUTES = frozenset({"sizeof", "alignof"})


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
    t = type(value)
    if t is IntValue or t is StrValue or t is BoolValue or t is CharValue \
            or t is ObjectValue:
        return value
    if isinstance(value, SomeValue):
        return unwrap_optional(value.value)
    if isinstance(value, ExpectedValue):
        if value.is_ok():
            return value.ok_value
        raise coded(2013, TypeError(
            f"unwrap of expected error: {value.err_value.display()}"))
    # A reference stands for what it points at wherever a value is
    # wanted; only assignment and @typeof look at the reference itself.
    if isinstance(value, Reference):
        return value.get()
    return value


def _enum_meets_number(ev) -> bool:
    """Whether an enum value may be compared with a bare number.

    An ordinary enum holds exactly its members, so asking whether one
    equals a number is a fair question with a plain answer: it matches
    or it does not.  A @flag enum's values are combinations of its
    members, which no bare number names, so the question is refused
    rather than answered -- `.ord()` is how a program asks for the
    bits, and asking for them is then written down.
    """
    if ev.enum_type.is_flag:
        raise coded(2826, TypeError(
            f"'{ev.enum_type.name}' is a @flag enum, so its values are "
            f"combinations of members that a bare number does not name; "
            f"write .ord() to compare the bits"))
    return True


def _unwrap_operand(value):
    # Most operands are already the plain thing an operator wants, and
    # asking costs less than the two calls that answer the same.
    t = type(value)
    if t is IntValue or t is StrValue or t is BoolValue or t is CharValue:
        return value
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


_BARE_GENERIC_RE = re.compile(r"\w+'")
_BARE_GENERIC_CACHE: dict = {}


def _is_bare_generic(type_name: str) -> bool:
    """Whether a type is nothing but a generic name, as T' is.

    Asked of every parameter of every call and of every return, so a
    program that names no generic at all still asks it tens of millions
    of times.  The answer depends on nothing but the spelling, and a
    program writes few spellings, so it is remembered; a stored False
    is told from nothing stored because only truth values are stored.
    """
    got = _BARE_GENERIC_CACHE.get(type_name)
    if got is None:
        got = _BARE_GENERIC_RE.fullmatch(type_name) is not None
        _BARE_GENERIC_CACHE[type_name] = got
    return got


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
_ARRAY_MUTATORS = frozenset({"push", "pop", "insert", "remove", "clear"})

# std methods that thread over containers, as @listable functions do.
_LISTABLE_STD_METHODS = frozenset({"sin", "cos", "sinpi"})

_ARRAY_METHODS: dict[str, int] = {
    "push": 1,
    "pop": 0,
    "insert": 2,
    "remove": 1,
    "get": 1,
    "iterate": 0,
}


# What a statement that has produced no resource holds: not None, so
# that registration is still on, and empty, so that releasing has
# nothing to do.  Shared, because it is never written to.
_NO_TEMPS: tuple = ()


# The modules the program declares.  Program-wide rather than an
# evaluator's own, as the units and the macros are: the definitions are
# installed through one evaluator and the program runs through another,
# and both have to see the same modules.
MODULES: set = set()


def register_modules(names) -> None:
    """Record the modules a program declares, replacing any before."""
    MODULES.clear()
    MODULES.update(names)


def _ancestors_of(module: str) -> list:
    """A module and the ones it is written inside, innermost first."""
    out = [module]
    while module:
        module = module.rsplit(".", 1)[0] if "." in module else ""
        out.append(module)
    return out


# Says a target subexpression was not evaluated, which is every
# target that has none: a bare name.
_MISSING = object()


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
        # True while an @expect body runs: its warnings are collected
        # for matching rather than reported to the user.
        self._collect_warnings: bool = False
        self._wrapping: bool = False
        self._catch_depth: int = 0
        self._loops: list[str | None] = []
        self._pure_func_name: str | None = None
        self._generic_map: dict[str, str] = {}
        self._comptime_vars: set[str] = set()
        # The module the function now running was written in, and every
        # module the program declares.  A name written unqualified is
        # looked for in that module and then in the ones it is written
        # inside, which is C++'s namespace lookup with a period.
        self._cur_module: str = ""
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
            "\N{DIVISION SIGN}": self._op_div,
            "%": self._op_mod,
            # Saturating arithmetic: the same sums, held at the edge of
            # the type rather than reported for leaving it.
            "\N{SQUARED PLUS}": self._op_sat_add,
            "\N{SQUARED MINUS}": self._op_sat_sub,
            "\N{SQUARED TIMES}": self._op_sat_mul,
            # The larger and the smaller of two numbers, as in APL.
            "\N{LEFT CEILING}": self._op_max,
            "\N{LEFT FLOOR}": self._op_min,
            "=": self._op_eq,
            "\N{NOT EQUAL TO}": self._op_neq,
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
            # Paired with the shifts by direction: ↻ turns the way «
            # moves, and ↺ the way » does.
            "↻": self._op_rotl,
            "↺": self._op_rotr,
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

    def _float_arith(self, value: float, width: str, symbol: str,
                     left: float, right: float, *,
                     may_underflow: bool = True) -> FloatValue:
        """The value of a float operation, once it is known to be one.

        A result the format cannot hold would be an infinity, and one
        too small for it to tell from zero would be a zero.  Either is
        a different number from the one the operation has, which is
        what integer overflow is reported for, so both are reported
        here.
        """
        from interp.value import check_float_arith
        return mk_float(
            check_float_arith(value, width, symbol, left, right,
                              may_underflow=may_underflow),
            width)

    def _op_add(self, left, right):
        """Addition: integers, floats, and strings (concatenation)."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return self._mk_int(lu.value + ru.value, resolve_width(lu.width, ru.width))
        ff = self._require_matching_numeric(lu, ru, "addition")
        if ff is not None:
            # A zero from a sum is exact: it says the two were equal.
            return self._float_arith(ff[0] + ff[1], ff[2], "+", ff[0], ff[1],
                                     may_underflow=False)
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
            return self._float_arith(ff[0] - ff[1], ff[2], "-", ff[0], ff[1],
                                     may_underflow=False)
        raise TypeError(f"subtraction expected int+int or float+float, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_mul(self, left, right):
        """Multiplication."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return self._mk_int(lu.value * ru.value, resolve_width(lu.width, ru.width))
        ff = self._require_matching_numeric(lu, ru, "multiplication")
        if ff is not None:
            return self._float_arith(ff[0] * ff[1], ff[2],
                                     "\N{MULTIPLICATION SIGN}", ff[0], ff[1])
        raise TypeError(f"multiplication expected int+int or float+float, got {type(lu).__name__}+{type(ru).__name__}")

    def _saturate(self, value: int, width: str, op_name: str) -> IntValue:
        """Hold a result at the nearest edge of its type.

        A width with no bounds — an untyped literal, or `int` — has no
        edge to be held at, so the result is exact.  That is not a
        failure of the operator: an arbitrary-precision sum is already
        the answer saturation would be protecting.
        """
        limits = int_limits(width)
        if limits is None:
            return IntValue(value, width)
        lo, hi = limits
        return IntValue(lo if value < lo else hi if value > hi else value,
                        width)

    def _sat_binop(self, left, right, op_name: str, combine):
        """Shared body of the saturating operators."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            width = resolve_width(lu.width, ru.width)
            return self._saturate(combine(lu.value, ru.value), width, op_name)
        # Saturation is about the edge of a stated range.  A float
        # already has an answer for a result that will not fit -- the
        # operation is reported -- and nothing else has a range at all,
        # so neither has a saturating form.
        raise coded(2224, TypeError(
            f"{op_name} is for integers, which state the range it holds "
            f"a result inside; got "
            f"{runtime_type_of(lu)} and {runtime_type_of(ru)}"))

    def _op_index_of(self, left, right):
        """Where in a container something is, counted from zero.

        The answer is optional because it may not be there at all: a
        position that is not in the container is not a number to
        invent, and ∅ says so where a sentinel would have to be
        remembered.  It carries the unit an index of that container
        carries, so what comes back can be used to look with.
        """
        container = _unwrap_operand(left)
        wanted = _unwrap_operand(right)
        if isinstance(container, StrValue):
            if isinstance(wanted, CharValue):
                found = container.value.find(wanted.char)
            elif isinstance(wanted, StrValue):
                # A run of characters is where it starts.
                found = container.value.find(wanted.value)
            else:
                raise coded(2710, TypeError(
                    f"\N{APL FUNCTIONAL SYMBOL IOTA}: a string is searched "
                    f"for a character or a string, not for "
                    f"{runtime_type_of(wanted)}"))
            return (none() if found < 0
                    else some(self._sizeof_result(found)))
        array = self._as_array(container)
        if array is None:
            raise coded(2711, TypeError(
                f"\N{APL FUNCTIONAL SYMBOL IOTA}: the left operand is "
                f"{self._value_type_name(container)}, and what is searched "
                f"is an array or a string"))
        # What is searched for has to be the kind of thing the container
        # holds, as ∊ asks it: answering "nowhere" would let a program
        # that has made a mistake about one of the two carry on
        # believing both.  A string container asks the same above.
        self._check_looked_for(array, wanted,
                               "\N{APL FUNCTIONAL SYMBOL IOTA}")
        for index, element in enumerate(array.values()):
            # Compared the way == compares, by going through the same
            # door: a unit that does not belong to the container is
            # refused here as it would be between the two operands,
            # rather than quietly matching nothing.
            same = self._apply_operator("=", element, right)
            if not isinstance(unwrap_optional(same), BoolValue):
                # The comparison answered element-wise, so the element
                # is itself a container: a position in it is not one
                # number, and there is nothing honest to answer.
                raise coded(2712, TypeError(
                    f"\N{APL FUNCTIONAL SYMBOL IOTA}: the left operand has "
                    f"more than one dimension, and a position in it is not "
                    f"one number; a row of it is searched on its own"))
            if to_bool(same):
                return some(self._sizeof_result(index, array.element_type))
        return none()

    @classmethod
    def _leaves(cls, array):
        """Every element of a container, past any nesting.

        A matrix holds rows and a row holds numbers, and what is in the
        matrix is what is in one of its rows.  Membership has an answer
        at any number of dimensions, which is why \N{SMALL ELEMENT OF}
        looks through all of them where \N{APL FUNCTIONAL SYMBOL IOTA}
        stops at one: a position has to say where, and this says only
        whether.
        """
        for element in array.values():
            inner = cls._as_array(element)
            if inner is None:
                yield element
            else:
                yield from cls._leaves(inner)

    def _check_looked_for(self, array, wanted, op: str):
        """Refuse looking in a container for what it cannot hold.

        Shared by ⍳ and ∊, which ask the same question of their
        operands and so have to ask it the same way.  A program looking
        for a string among some numbers has made a mistake about one of
        the two, and an answer -- nowhere, or no -- would let it carry
        on believing both.

        The rule is the language's own for whether two scalars are the
        same kind of thing, so a width still meets another width and an
        untyped number still settles on what the container holds.  What
        the kinds admit is then compared by going through ==, where the
        unit rules already live.
        """
        element_type = self._leaf_element_type(array)
        if element_type is None:
            return
        mismatch = _scalar_kind_mismatch(wanted, element_type)
        if mismatch is not None:
            raise coded(2713, TypeError(
                f"{op}: the container holds {element_type}, and what is "
                f"looked for is {mismatch}"))

    @classmethod
    def _leaf_element_type(cls, array):
        """What a container holds, past any nesting."""
        while True:
            values = array.values()
            if not values:
                return array.element_type
            inner = cls._as_array(values[0])
            if inner is None:
                return array.element_type
            array = inner

    def _op_element_of(self, left, right):
        """Whether what is on the left is somewhere on the right.

        One thing is asked about at a time, and the answer is one bool.
        The right operand is looked through whole however many
        dimensions it has, which is the question ⍳ cannot answer for a
        matrix: a position has to say where, and this says only
        whether.
        """
        if self._as_array(left) is not None:
            raise coded(2714, TypeError(
                f"\N{SMALL ELEMENT OF}: the left operand is an array, and "
                f"what is looked for is one thing; each of them is asked "
                f"about on its own"))
        wanted = _unwrap_operand(left)
        container = _unwrap_operand(right)
        if isinstance(container, StrValue):
            if isinstance(wanted, CharValue):
                return mk_bool(wanted.char in container.value)
            if isinstance(wanted, StrValue):
                # A string holds characters, so a run of them is not one
                # of the things it holds.  Whether one is there is a
                # question about where it starts, which ⍳ answers.
                raise coded(2715, TypeError(
                    f"\N{SMALL ELEMENT OF}: a string holds characters, and a "
                    f"run of them is not one of them; "
                    f"\N{APL FUNCTIONAL SYMBOL IOTA} says where a run starts"))
            raise coded(2716, TypeError(
                f"\N{SMALL ELEMENT OF}: a string holds characters, and what "
                f"is looked for is {self._value_type_name(wanted)}"))
        if isinstance(container, ObjectValue) \
                and isinstance(container.obj, HashValue):
            # A hash is looked through by its keys, which is what it is
            # asked about: what it holds against them is read with [].
            return mk_bool(container.obj.has(wanted))
        if isinstance(container, ObjectValue) \
                and isinstance(container.obj, SetValue):
            return mk_bool(container.obj.has(wanted))
        array = self._as_array(container)
        if array is None:
            raise coded(2717, TypeError(
                f"\N{SMALL ELEMENT OF}: the right operand is "
                f"{self._value_type_name(container)}, and what is looked "
                f"through is a vector, a matrix, a string, a dictionary or a set"))
        self._check_looked_for(array, wanted, "\N{SMALL ELEMENT OF}")
        for element in self._leaves(array):
            # Compared the way == compares, as ⍳ compares, so a unit
            # that does not belong is refused rather than found missing.
            if to_bool(self._apply_operator("=", element, left)):
                return mk_bool(True)
        return mk_bool(False)

    def _op_max(self, left, right):
        """The larger of two numbers (\N{LEFT CEILING})."""
        return self._op_extremum(left, right, "maximum (\N{LEFT CEILING})",
                                 larger=True)

    def _op_min(self, left, right):
        """The smaller of two numbers (\N{LEFT FLOOR})."""
        return self._op_extremum(left, right, "minimum (\N{LEFT FLOOR})",
                                 larger=False)

    def _op_extremum(self, left, right, op_name: str, *, larger: bool):
        """Answer with whichever operand the comparison picks.

        The answer is one of the operands rather than something
        computed from both, so it needs no range of its own: whatever
        width the two settle on holds a value that already fitted in
        one of them.

        The operands must be the same kind of number, as they must for
        addition.  The larger of a length and a count is not a question
        with an answer, and an integer and a float are compared exactly
        where a tolerant comparison is what a program usually wants.
        """
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            keep = lu.value if (lu.value >= ru.value) == larger else ru.value
            return self._mk_int(keep, resolve_width(lu.width, ru.width))
        ff = self._require_matching_numeric(lu, ru, op_name)
        if ff is not None:
            l_val, r_val, width = ff
            # A NaN is not larger or smaller than anything, so it is
            # the answer rather than something that depends on which
            # side of the operator it was written -- IEEE 754-2019's
            # maximum and minimum, not Python's max and min.
            if l_val != l_val or r_val != r_val:
                return mk_float(float("nan"), width)
            return mk_float(l_val if (l_val >= r_val) == larger else r_val,
                            width)
        raise coded(2011, TypeError(
            f"{op_name} expected numeric types, got "
            f"{type(lu).__name__}+{type(ru).__name__}"))

    def _op_sat_add(self, left, right):
        """Saturating addition."""
        return self._sat_binop(left, right, "saturating addition (⊞)",
                               lambda a, b: a + b)

    def _op_sat_sub(self, left, right):
        """Saturating subtraction."""
        return self._sat_binop(left, right, "saturating subtraction (⊟)",
                               lambda a, b: a - b)

    def _op_sat_mul(self, left, right):
        """Saturating multiplication."""
        return self._sat_binop(left, right,
                               "saturating multiplication (⊠)",
                               lambda a, b: a * b)

    def _op_div(self, left, right):
        """Division: integer (truncates toward zero, returns ExpectedValue) or float."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            if ru.value == 0:
                return self._division_error()
            # Exact integer division, truncating toward zero.  Going
            # through a float loses precision past 2^53 and answered
            # wrongly for wide values.
            result = lu.value // ru.value
            if result < 0 and result * ru.value != lu.value:
                result += 1
            return ExpectedValue.ok(self._mk_int(result, resolve_width(lu.width, ru.width)))
        ff = self._require_matching_numeric(lu, ru, "division")
        if ff is not None:
            if ff[1] == 0.0:
                return self._division_error()
            return self._float_arith(ff[0] / ff[1], ff[2],
                                     "\N{DIVISION SIGN}", ff[0], ff[1])
        raise TypeError(f"division expected int+int or float+float, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_mod(self, left, right):
        """Remainder (truncation toward zero): a % b = a - trunc(a/b)*b.  Returns ExpectedValue."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            if ru.value == 0:
                return self._division_error()
            quot = lu.value // ru.value
            if quot < 0 and quot * ru.value != lu.value:
                quot += 1
            return ExpectedValue.ok(self._mk_int(lu.value - quot * ru.value, resolve_width(lu.width, ru.width)))
        ff = self._require_matching_numeric(lu, ru, "remainder")
        if ff is not None:
            import math
            if ff[1] == 0.0:
                return self._division_error()
            return mk_float(math.fmod(ff[0], ff[1]), ff[2])
        raise TypeError(f"remainder expected int+int or float+float, got {type(lu).__name__}+{type(ru).__name__}")

    def _float_power(self, base: float, exponent, width: str) -> FloatValue:
        """A power of floats, checked as the other operations are.

        Python answers a power too large for a float by raising rather
        than by producing an infinity, so the two ways of leaving the
        range meet here and are reported alike.
        """
        from interp.value import check_float_arith
        try:
            value = base ** exponent
        except OverflowError:
            value = math.inf if base > 0 or int(exponent) % 2 == 0 else -math.inf
        return mk_float(
            check_float_arith(value, width, "\N{UPWARDS ARROW}", base,
                              float(exponent), may_underflow=True),
            width)

    def _op_pow(self, left, right):
        """Exponentiation: int↑int, float↑float, or float↑int."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            if ru.value < 0:
                raise TypeError("integer exponentiation requires non-negative exponent")
            return self._mk_int(lu.value ** ru.value, lu.width)
        if isinstance(lu, FloatValue) and isinstance(ru, FloatValue):
            return self._float_power(lu.value, ru.value,
                                     resolve_float_width(lu.width, ru.width))
        if isinstance(lu, FloatValue) and isinstance(ru, IntValue):
            return self._float_power(lu.value, ru.value, lu.width)
        if isinstance(lu, IntValue) and isinstance(ru, FloatValue):
            raise coded(2225, TypeError(
                f"exponentiation requires matching types, got {lu.width} and {ru.width}"))
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
        raise coded(2612, TypeError(
            f"{what}: cannot compare an optional with a plain value; write "
            f"\N{THERE EXISTS}(v) to compare against a present value, "
            f"\N{EMPTY SET} against an absent one, or ?? to supply a default"))

    _APPROX_OPS = frozenset("≅≇⪅⪆⪉⪊")

    # What two sets make between them.  Both operands are the container
    # rather than a stand-in for what is in it, so these are not
    # threaded, as ⧺ and ∊ are not.
    _SET_OPS = frozenset({"\N{UNION}", "\N{INTERSECTION}",
                          "\N{SET MINUS}"})

    # Whether one set is held inside another.  Both operands are the
    # container here too, so these are dispatched with the ones above
    # rather than threaded.
    _SUBSET_OPS = frozenset({"\N{SUBSET OF}",
                             "\N{SUBSET OF OR EQUAL TO}"})

    # Every operator that means for a container what it means for one of
    # the things in it, and so is threaded over one that it is handed.
    # ⧺, ⍳ and ∊ take a container as the operand rather than as a
    # stand-in for its elements; they are dispatched before threading
    # can see them, so the two statements cannot drift apart.
    _LISTABLE_BINOPS = frozenset({
        "+", "-", "\N{MULTIPLICATION SIGN}", "\N{DIVISION SIGN}", "%",
        "\N{SQUARED PLUS}", "\N{SQUARED MINUS}", "\N{SQUARED TIMES}",
        "\N{LEFT CEILING}", "\N{LEFT FLOOR}",
        "=", "\N{NOT EQUAL TO}", "<", ">", "<=", ">=",
        "and", "or",
        "<<", ">>", "&", "^", "|", "«", "»", "↻", "↺",
        "∧", "∨", "⊕", "⊼", "⊽", "\N{UPWARDS ARROW}",
    }) | _APPROX_OPS

    # What a threaded operand is called when the lengths disagree.
    _OPERAND_NAMES = ("the left operand", "the right operand")

    # The unary operators that mean for a container what they mean for
    # one of the things in it.  `not` is left out: the language keeps it
    # apart from ¬ as the short-circuit one, and it answers a bool for
    # whatever it is given rather than one of the same kind.
    _LISTABLE_UNOPS = frozenset({
        "\N{SUPERSCRIPT MINUS}", "~", "\N{NOT SIGN}",
        "\N{SQUARE ROOT}", "\N{CUBE ROOT}", "\N{FOURTH ROOT}",
        "\N{LEFT CEILING}", "\N{LEFT FLOOR}",
    })

    def _approx_alike(self, a: float, b: float) -> bool:
        """Whether two numbers are alike to within the comparison tolerance.

        The tolerance is a fraction of the larger of the two, as APL's
        ⎕CT is, so what counts as alike scales with the numbers being
        compared.  One consequence is that nothing but zero is alike to
        zero, since a fraction of zero is zero.
        """
        if a == b:
            return True
        tolerance = getattr(std, "comparison_tolerance", 0.0)
        return abs(a - b) <= tolerance * max(abs(a), abs(b))

    def _op_approx(self, op: str, left, right):
        """A comparison made to within the comparison tolerance."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        a, b, _ = self._promote_to_float(lu, ru)
        if a is None:
            if isinstance(lu, IntValue) and isinstance(ru, IntValue):
                raise coded(2226, TypeError(
                    f"{op}: an approximate comparison is for floating-point "
                    f"values; integers are exact, so compare them with the "
                    f"exact operator"))
            raise coded(2227, TypeError(
                f"{op}: an approximate comparison expects numbers, got "
                f"{self._value_type_name(lu)} and {self._value_type_name(ru)}"))
        alike = self._approx_alike(a, b)
        if op == "≅":
            return mk_bool(alike)
        if op == "≇":
            return mk_bool(not alike)
        if op == "⪅":
            return mk_bool(alike or a < b)
        if op == "⪆":
            return mk_bool(alike or a > b)
        if op == "⪉":
            return mk_bool(a < b and not alike)
        return mk_bool(a > b and not alike)

    def _op_eq(self, left, right):
        """Equality comparison."""
        if type(left) is IntValue and type(right) is IntValue \
                and left.width == right.width:
            return TRUE_VALUE if left.value == right.value else FALSE_VALUE
        self._reject_mixed_optional(left, right, "=")
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
        if isinstance(lu, SyntaxValue) or isinstance(ru, SyntaxValue):
            # Reached through an optional, which is settled above
            # before what it holds is looked at.
            return self._op_syntax_eq("=", lu, ru)
        if isinstance(lu, EnumValue) and isinstance(ru, EnumValue):
            if lu.enum_type is not ru.enum_type:
                raise coded(2810, TypeError(
                    f"cannot compare enum '{lu.enum_type.name}' "
                    f"with enum '{ru.enum_type.name}'"))
            return mk_bool(lu.value == ru.value)
        if isinstance(lu, EnumValue) and isinstance(ru, IntValue):
            return mk_bool(_enum_meets_number(lu) and lu.value == ru.value)
        if isinstance(lu, IntValue) and isinstance(ru, EnumValue):
            return mk_bool(_enum_meets_number(ru) and lu.value == ru.value)
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
        if isinstance(lu, CharValue) and isinstance(ru, CharValue):
            return mk_bool(lu.code == ru.code)
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
        if isinstance(lu, CharValue) and isinstance(ru, CharValue):
            return mk_bool(lu.code < ru.code)
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
        if isinstance(lu, CharValue) and isinstance(ru, CharValue):
            return mk_bool(lu.code > ru.code)
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
        if isinstance(lu, CharValue) and isinstance(ru, CharValue):
            return mk_bool(lu.code <= ru.code)
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
        if isinstance(lu, CharValue) and isinstance(ru, CharValue):
            return mk_bool(lu.code >= ru.code)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_bool(lu.value >= ru.value)
        lf, rf, _ = self._promote_to_float(lu, ru)
        if lf is not None:
            return mk_bool(lf >= rf)
        raise TypeError(f"greater-equal expected numeric types, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_and(self, left, right):
        """Short-circuit boolean and."""
        lu = _unwrap_operand(left)
        if not self._logic_bool(lu):
            return mk_bool(False)
        ru = _unwrap_operand(right)
        return mk_bool(self._logic_bool(ru))

    def _op_or(self, left, right):
        """Short-circuit boolean or."""
        lu = _unwrap_operand(left)
        if self._logic_bool(lu):
            return mk_bool(True)
        ru = _unwrap_operand(right)
        return mk_bool(self._logic_bool(ru))

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
                raise coded(2811, TypeError(f"bitwise operations require @flag enum, got '{lu.enum_type.name}'"))
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
                raise coded(2812, TypeError(f"bitwise operations require @flag enum, got '{lu.enum_type.name}'"))
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
                raise coded(2813, TypeError(
                    f"cannot combine enum '{lu.enum_type.name}' with '{ru.enum_type.name}'"))
            if not lu.enum_type.is_flag:
                raise coded(2814, TypeError(f"bitwise operations require @flag enum, got '{lu.enum_type.name}'"))
            return EnumValue(lu.enum_type, lu.value | ru.value)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            return mk_int_wrap(lu.value | ru.value, resolve_width(lu.width, ru.width))
        raise TypeError(f"bitwise-or expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _rotation_width(self, lu, ru, op_name: str) -> tuple[int, int]:
        """The width a rotation turns within, and how far it turns.

        A rotation moves every bit of the representation around, so the
        width is the operand's own and the count is taken modulo it:
        turning all the way round is where it started, which is a
        harmless thing to write rather than a mistake.  This is where a
        rotation parts company with a shift, which loses the bits it
        moves past the end and so refuses a count that would lose them
        all.
        """
        bits = _TYPE_BITS.get(lu.width)
        if bits is None:
            raise coded(2228, TypeError(
                f"{op_name}: '{lu.width}' has no width to turn within; "
                f"rotate a sized integer"))
        return bits, ru.value % bits

    def _op_rotl(self, left, right):
        """Rotate left within the operand's own width."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            bits, n = self._rotation_width(lu, ru, "rotate-left")
            mask = (1 << bits) - 1
            val = lu.value & mask
            result = ((val << n) | (val >> (bits - n))) & mask
            return mk_int_wrap(result, lu.width)
        raise TypeError(f"rotate-left expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    def _op_rotr(self, left, right):
        """Rotate right within the operand's own width."""
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, IntValue) and isinstance(ru, IntValue):
            bits, n = self._rotation_width(lu, ru, "rotate-right")
            mask = (1 << bits) - 1
            val = lu.value & mask
            result = ((val >> n) | (val << (bits - n))) & mask
            return mk_int_wrap(result, lu.width)
        raise TypeError(f"rotate-right expected int+int, got {type(lu).__name__}+{type(ru).__name__}")

    @staticmethod
    def _logic_bool(val) -> bool:
        """The truth value a logic operator was handed.

        Only bool is accepted: a number is a quantity, not an answer,
        and the program that means "is it nonzero" writes the
        comparison.  Anything else is an error naming what arrived.
        """
        if isinstance(val, BoolValue):
            return val.value
        from interp.value import runtime_type_of
        raise coded(2229, TypeError(
            f"a logic operator takes truth values, but this operand is "
            f"{runtime_type_of(val)}; a number asks its question with a "
            f"comparison, as 'x ≠ 0'"))

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

    def _checked_key(self, key, key_type, key_unit):
        """Measure a key against what the others were, and refuse one
        that cannot be remembered at all."""
        if hash_key(key) is None:
            raise coded(2815, TypeError(
                f"{self._value_type_name(key)} cannot be a key: a key is "
                f"remembered by what it is, so it has to be one of the "
                f"things the language compares exactly -- a number, a "
                f"character, a string, a truth value, an enum"))
        if key_type is not None:
            return coerce_to_type(key, key_type, key_unit, self._mk_int)
        return key

    def _op_container_eq(self, op: str, left, right):
        """Whether two dictionaries or two sets hold the same things.

        Order is not part of it.  A hash and a set have no order of
        their own -- what they keep is the order things arrived in, so
        that walking one is repeatable -- and two that hold the same
        things are the same whichever way each was built up.
        """
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        same = self._same_value(lu, ru, strict=True)
        return mk_bool(same if op == "=" else not same)

    def _same_value(self, one, other, strict: bool = False) -> bool:
        """Whether two values hold the same thing, however deep it sits.

        Used where a container is compared whole, which is the one
        place equality has to reach through an array rather than being
        asked of each of its elements.
        """
        one = _unwrap_operand(one)
        other = _unwrap_operand(other)
        for kind in (HashValue, SetValue):
            first = (one.obj if isinstance(one, ObjectValue)
                     and isinstance(one.obj, kind) else None)
            second = (other.obj if isinstance(other, ObjectValue)
                      and isinstance(other.obj, kind) else None)
            if first is None and second is None:
                continue
            if first is None or second is None:
                if strict:
                    raise coded(2230, TypeError(
                        f"{self._value_type_name(one)} and "
                        f"{self._value_type_name(other)} are not compared "
                        f"with each other: they hold different kinds of "
                        f"thing, so neither could be the other"))
                return False
            if strict:
                self._same_held(kind, first, second)
            if first.sizeof != second.sizeof:
                return False
            if kind is SetValue:
                return all(second.has(v) for v in first.values())
            return all(second.has(k)
                       and self._same_value(second.get(k), v)
                       for k, v in first.pairs())
        first = self._as_array(one)
        second = self._as_array(other)
        if first is not None or second is not None:
            if first is None or second is None or first.sizeof != second.sizeof:
                return False
            return all(self._same_value(first.get(i), second.get(i))
                       for i in range(first.sizeof))
        return to_bool(self._op_eq(one, other))

    def _same_held(self, kind, first, second):
        """Refuse comparing two containers that cannot hold the same."""
        attrs = ((("key", "key_type"), ("value", "value_type"))
                 if kind is HashValue else (("value", "value_type"),))
        what = "dictionary" if kind is HashValue else "set"
        for name, attr in attrs:
            one, other = getattr(first, attr), getattr(second, attr)
            if one is not None and other is not None and one != other:
                raise coded(2718, TypeError(
                    f"a {what} holds one type of {name}, so two are compared "
                    f"only where they hold the same, but the left holds "
                    f"{one} and the right holds {other}"))

    def _op_subset(self, op: str, left, right):
        """Whether everything in the one is in the other.

        ⊆ asks that and no more; ⊂ asks it of a set that is not the
        whole of the other, which is what "proper" means and what
        makes ⊂ false where the two hold the same things.
        """
        first, second = self._two_sets(op, left, right)
        inside = all(second.has(value) for value in first.values())
        if op == "\N{SUBSET OF OR EQUAL TO}":
            return mk_bool(inside)
        return mk_bool(inside and first.sizeof < second.sizeof)

    def _two_sets(self, op: str, left, right):
        """The two sets an operator between sets was given."""
        sets = []
        for side, value in (("left", _unwrap_operand(left)),
                            ("right", _unwrap_operand(right))):
            if isinstance(value, ObjectValue) \
                    and isinstance(value.obj, SetValue):
                sets.append(value.obj)
                continue
            raise coded(2231, TypeError(
                f"{op}: the {side} operand is "
                f"{self._value_type_name(value)}, and {op} is asked of two "
                f"sets"))
        first, second = sets
        if first.value_type is not None and second.value_type is not None \
                and first.value_type != second.value_type:
            raise coded(2719, TypeError(
                f"{op}: a set holds one type of value, so two are asked "
                f"about together only where they hold the same, but the "
                f"left holds {first.value_type} and the right holds "
                f"{second.value_type}"))
        return first, second

    def _op_set(self, op: str, left, right):
        """What two sets make between them.

        ∪ is what is in either, ∩ what is in both, ∖ what is in the
        first and not the second.  Order is kept, as it is everywhere
        else these are walked: what came from the left comes first, in
        the order it was in.
        """
        first, second = self._two_sets(op, left, right)
        built = SetValue(value_type=first.value_type or second.value_type)
        if op == "\N{UNION}":
            for value in first.values():
                built.put(value)
            for value in second.values():
                built.put(value)
        elif op == "\N{INTERSECTION}":
            for value in first.values():
                if second.has(value):
                    built.put(value)
        else:
            for value in first.values():
                if not second.has(value):
                    built.put(value)
        return ObjectValue(built)

    def _concat_hashes(self, lu, ru):
        """Join two dictionaries, the right-hand value winning a shared key.

        That is the one thing joining two dictionaries says: ∪ answers what
        two sets hold between them and never has to choose, because a
        set holds no more about a value than that it is there.  A hash
        does, so where both hold the same key one of the two values has
        to be the answer -- and it is the right-hand one, which makes
        `defaults ⧺ overrides` read the way it is meant.

        A key keeps the place it first had.  What the right operand
        says is what the key holds, not where it sits.
        """
        sides = []
        for side, value in (("left", lu), ("right", ru)):
            if isinstance(value, ObjectValue) \
                    and isinstance(value.obj, HashValue):
                sides.append(value.obj)
                continue
            raise coded(2720, TypeError(
                f"\N{DOUBLE PLUS}: the {side} operand is "
                f"{self._value_type_name(value)}, and a dictionary joins a dictionary"))
        first, second = sides
        for name, attr in (("key", "key_type"), ("value", "value_type")):
            one, other = getattr(first, attr), getattr(second, attr)
            if one is not None and other is not None and one != other:
                raise coded(2721, TypeError(
                    f"\N{DOUBLE PLUS}: a dictionary holds one type of {name}, so "
                    f"two joined hold the same one, but the left holds "
                    f"{one} and the right holds {other}"))
        built = HashValue(key_type=first.key_type or second.key_type,
                          value_type=first.value_type or second.value_type)
        for key, value in first.pairs():
            built.put(key, value)
        for key, value in second.pairs():
            built.put(key, value)
        return ObjectValue(built)

    def _op_halves(self, op: str, operand):
        """What a dictionary holds: ⊃ its keys, ⊇ what it holds against them.

        Both answer an array, in the order the entries arrived, so what
        comes back is walked and indexed the way anything else is.
        """
        held = _unwrap_operand(operand)
        if isinstance(held, ObjectValue) and isinstance(held.obj, HashValue):
            hv = held.obj
            if op == "\N{SUPERSET OF}":
                return ObjectValue(ArrayValue(hv.keys(),
                                              element_type=hv.key_type))
            return ObjectValue(ArrayValue(hv.values(),
                                          element_type=hv.value_type))
        if isinstance(held, ObjectValue) and isinstance(held.obj, SetValue):
            if op == "\N{SUPERSET OF}":
                raise coded(2722, TypeError(
                    "\N{SUPERSET OF}: a set holds values rather than holding "
                    "them against keys, so it has none to ask for; "
                    "\N{SUPERSET OF OR EQUAL TO} answers what is in it"))
            return ObjectValue(ArrayValue(held.obj.values(),
                                          element_type=held.obj.value_type))
        raise coded(2723, TypeError(
            f"{op}: what a dictionary holds is a question for a dictionary"
            f"{' or a set' if op == chr(0x2287) else ''}, and this is "
            f"{self._value_type_name(held)}"))

    def _check_conditions(self, func, conditions, result=None):
        """Hold a function to what it said it holds to.

        A precondition is read where the parameters are bound, so it
        says what the caller has to have got right.  A postcondition is
        read where the answer is, so it says what the function got
        right, and may name the answer to say it about.

        A condition that does not hold is reported at the condition,
        which is the sentence the programmer wrote about what should be
        true -- the reader is shown the claim rather than the arithmetic
        that broke it.
        """
        if not conditions:
            return
        semantic = contract_semantic()
        # ignore does not read the condition at all, so nothing it
        # would have said -- including that it could not be read -- is
        # said.
        if semantic == "ignore":
            return
        for condition in conditions:
            if condition.name is not None:
                self.env.define(condition.name, result)
            try:
                held = self.eval_expr(condition.expr)
            except Exception as e:
                # The condition could not be read at all, which is a
                # violation of it in its own right: what it claims is
                # not known to be true.
                self._contract_violation(func, condition, semantic,
                                         strip_position_prefix(str(e)))
                continue
            unwrapped = unwrap_optional(held)
            if not isinstance(unwrapped, BoolValue):
                # Not a violation but a mistake in the condition, which
                # no semantic makes true and none is asked about.
                raise coded(2613, TypeError(
                    f"{func.name}: a @{condition.which} says what is true, "
                    f"so it answers a truth value, and this one answers "
                    f"{self._value_type_name(unwrapped)}"))
            if unwrapped.value:
                continue
            self._contract_violation(func, condition, semantic, None)

    def _contract_violation(self, func, condition, semantic: str,
                            unreadable: str | None) -> None:
        """Do what the chosen semantic says a broken condition does.

        `unreadable` is what went wrong where the condition could not be
        read, and None where it was read and answered false.  C++26
        calls those two the detection modes, and both are violations:
        a condition that cannot be read has not been kept to.

        observe reports and the run carries on; enforce reports and the
        run stops; quick-enforce stops without reporting, which is the
        whole of what makes it quick.
        """
        which = ("a precondition" if condition.which == "pre"
                 else "a postcondition")
        if unreadable is not None:
            message = (f"{func.name}: {which} could not be read, so what it "
                       f"claims is not known to hold: {unreadable}")
        else:
            blame = ("the caller did not" if condition.which == "pre"
                     else "the function did not")
            message = (f"{func.name}: {which} does not hold, so {blame} keep "
                       f"to what {func.name} says it needs")
        if semantic == "quick-enforce":
            # Nothing is reported: the point of this one is that the
            # check costs a test and a trap and nothing else.
            raise ProgramAbort(resolve_abort_signal(0))
        if semantic == "observe":
            # Reported as a warning whatever -Werror says: asking to
            # observe is asking for the run to carry on, and a
            # diagnostic that said error while the program kept going
            # would be saying two things.  Asking for both is asking
            # for enforce, which is spelled by asking for enforce.
            report_runtime_diagnostic(message, condition.pos,
                                      level="warning",
                                      call_stack=self._call_stack)
            return
        raise coded(2614, ContractError(message, condition.pos))

    @staticmethod
    def _ast_fields(node) -> tuple[str, ...]:
        """The names of what a node holds, however the node stores them."""
        if hasattr(node, "__dict__"):
            names = tuple(vars(node))
        else:
            names = tuple(getattr(type(node), "__slots__", ()))
        return tuple(n for n in names if n != "pos")

    def _op_syntax_eq(self, op: str, left, right):
        """Whether two pieces of the program say the same thing.

        Positions are not part of it: what is compared is what was
        written, not where.  So `e.head() = ※\N{MULTIPLICATION SIGN}` asks whether the
        expression applies multiplication, whoever wrote it and
        wherever.
        """
        if not (isinstance(left, SyntaxValue) and isinstance(right, SyntaxValue)):
            other = right if isinstance(left, SyntaxValue) else left
            raise TypeError(
                f"a piece of the program can be compared with another "
                f"piece of the program, and this is "
                f"{self._value_type_name(other)}")
        same = _alike_trees(
            left.body if left.is_block else left.node,
            right.body if right.is_block else right.node)
        if left.is_block != right.is_block:
            same = False
        return mk_bool(same if op == "=" else not same)

    def _call_syntax_method(self, piece: SyntaxValue, name: str, args):
        """What a piece of the program answers about itself.

        Enough to take apart what a macro is handed: what kind of thing
        it is, the name it reads where it is one, and the factors of a
        product however deeply the parser nested them.
        """
        if name == "kind":
            if args:
                raise TypeError("syntax.kind takes no arguments")
            if piece.is_block:
                return mk_str("block")
            return mk_str(_SYNTAX_KINDS.get(type(piece.node).__name__,
                                            type(piece.node).__name__))
        if name == "name":
            if args:
                raise TypeError("syntax.name takes no arguments")
            node = piece.node
            if isinstance(node, VarRef):
                return some(mk_str(node.name))
            if isinstance(node, GetAttr) and isinstance(node.obj, VarRef):
                return some(mk_str(f"{node.obj.name}.{node.attr}"))
            if isinstance(node, OperatorRef):
                # An operator is named by the glyph that performs it,
                # which is what ※ in front of one refers to.
                return some(mk_str(node.op))
            return none()
        if name == "head":
            if args:
                raise TypeError("syntax.head takes no arguments")
            if piece.is_block:
                return SyntaxValue(node=VarRef("block"))
            return SyntaxValue(node=_head_of(piece.node))
        if name == "arguments":
            if args:
                raise TypeError("syntax.arguments takes no arguments")
            return ObjectValue(ArrayValue(
                [SyntaxValue(node=a) for a in _arguments_of(piece.node)],
                element_type="syntax"))
        raise AttributeError(
            f"a piece of the program has no method '{name}'; it answers "
            f"kind(), name(), head() and arguments()")

    def _eval_quote(self, node: Quote):
        """Answer the tree a quote holds, with the $ parts put in.

        The tree is copied, so two evaluations of the same quote answer
        two pieces of program that can be taken apart without either
        being changed by what happens to the other.
        """
        import copy as _copy

        made = _copy.deepcopy(node.tree)
        made = self._fill_splices(made)
        if node.is_block:
            return SyntaxValue(body=made if isinstance(made, list) else [made])
        return SyntaxValue(node=made)

    def _fill_splices(self, node):
        """Replace every $ in a copied tree with what it answers."""
        if isinstance(node, Splice):
            return self._spliced_tree(self.eval_expr(node.expr))
        if isinstance(node, list):
            made = []
            for item in node:
                filled = self._fill_splices(item)
                if isinstance(filled, list):
                    made.extend(filled)
                else:
                    made.append(filled)
            return made
        if isinstance(node, tuple):
            return tuple(self._fill_splices(item) for item in node)
        if type(node).__module__ != "interp.ast":
            return node
        for name in self._ast_fields(node):
            setattr(node, name, self._fill_splices(getattr(node, name, None)))
        return node

    def _spliced_tree(self, value):
        """The tree a value stands for where it is put into a program.

        A piece of program is itself; a number, a string or a truth
        value is what a program would have to write to mean it, which
        is what lets a macro compute a constant and put it back.
        """
        value = unwrap_optional(value)
        if isinstance(value, SyntaxValue):
            return value.body if value.is_block else value.node
        if isinstance(value, IntValue):
            return IntLit(value.value, value.width)
        if isinstance(value, FloatValue):
            return FloatLit(value.value, value.width)
        if isinstance(value, StrValue):
            return StrLit(value.value)
        if isinstance(value, BoolValue):
            return BoolLit(value.value)
        raise TypeError(
            f"$ puts a piece of program or a number, a string or a truth "
            f"value into one, and this is {self._value_type_name(value)}")

    def _op_length(self, operand):
        """How many things are in it (#).

        The outer dimension, whatever it is given: a matrix answers how
        many rows it has rather than how wide they are, since that is
        the one number every container has.  A row's own length is
        asked of the row.

        Not threaded, for the same reason.  # asks for a container, and
        a container of containers is still one container -- there is
        nothing deeper than what it asked for, so there is nothing to
        take apart.
        """
        unwrapped = _unwrap_operand(operand)
        if isinstance(unwrapped, StrValue):
            return self._sizeof_result(len(unwrapped.value))
        if isinstance(unwrapped, TupleValue):
            return self._sizeof_result(len(unwrapped.elements))
        if isinstance(unwrapped, ObjectValue) \
                and isinstance(unwrapped.obj, (HashValue, SetValue)):
            return self._sizeof_result(unwrapped.obj.sizeof)
        array = self._as_array(unwrapped)
        if array is not None:
            return self._sizeof_result(array.sizeof, array.element_type)
        raise coded(2724, TypeError(
            f"#: how many things are in it is a question for an array, a "
            f"string, a tuple, a dictionary or a set, and this is "
            f"{self._value_type_name(unwrapped)}"))

    def _apply_unary(self, op: str, operand):
        """Apply a unary operator to the value it was given.

        Threaded over an operand deeper than the operator asks
        for, as a binary operator is: what ⁻ means for a number it
        means for each of a row of them.  Every one of these asks
        for one value, so anything deeper is a container of what
        it asks for.
        """
        if op == "#":
            return self._op_length(operand)
        if op in ("\N{SUPERSET OF}", "\N{SUPERSET OF OR EQUAL TO}"):
            return self._op_halves(op, operand)
        if op in self._LISTABLE_UNOPS:
            threaded = self._thread_level(
                op, ("the operand",), [operand], (0,),
                lambda sub: self._apply_unary(op, sub[0]),
                noun="operands")
            if threaded is not None:
                return threaded
        if op == "⁻":
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
        if op in ("\N{LEFT CEILING}", "\N{LEFT FLOOR}"):
            unwrapped = unwrap_optional(operand)
            if isinstance(unwrapped, CharValue):
                # One character's upper case can be more than one
                # character -- ß is SS -- so what comes back is a
                # string, and the operand says so too.
                raise coded(2725, TypeError(
                    f"{op} answers with a string, so it asks for "
                    f"one: a character's case is written "
                    f"{op}c.str(), since the upper case of one "
                    f"character can be more than one character"))
            if not isinstance(unwrapped, StrValue):
                raise coded(2232, TypeError(
                    f"{op} in front of an operand is the case of "
                    f"text, and this one is "
                    f"{runtime_type_of(unwrapped)}; the larger and the "
                    f"smaller of two numbers are written between them"))
            return mk_str(unwrapped.value.upper()
                          if op == "\N{LEFT CEILING}"
                          else unwrapped.value.lower())
        if op == "~":
            unwrapped = unwrap_optional(operand)
            if isinstance(unwrapped, UnitValue):
                inner = unwrapped.inner
                if isinstance(inner, IntValue):
                    return UnitValue(mk_int_wrap(~inner.value, inner.width), unwrapped.unit)
                raise TypeError(f"bitwise-not expected int, got {type(inner).__name__}")
            if isinstance(unwrapped, EnumValue):
                if not unwrapped.enum_type.is_flag:
                    raise coded(2816, TypeError(
                        f"bitwise-not requires @flag enum, got '{unwrapped.enum_type.name}'"))
                all_bits = 0
                for v in unwrapped.enum_type.members.values():
                    all_bits |= v
                return EnumValue(unwrapped.enum_type, ~unwrapped.value & all_bits)
            if isinstance(unwrapped, IntValue):
                return mk_int_wrap(~unwrapped.value, unwrapped.width)
            raise TypeError(f"bitwise-not expected int, got {type(unwrapped).__name__}")
        if op == "¬":
            unwrapped = unwrap_optional(operand)
            return mk_bool(not self._logic_bool(unwrapped))
        if op == "not":
            return mk_bool(not self._logic_bool(_unwrap_operand(operand)))
        if op in ("\N{SQUARE ROOT}", "\N{CUBE ROOT}", "\N{FOURTH ROOT}"):
            import math
            degree = {"\N{SQUARE ROOT}": 2, "\N{CUBE ROOT}": 3, "\N{FOURTH ROOT}": 4}[op]
            unwrapped = unwrap_optional(operand)
            if isinstance(unwrapped, UnitValue):
                inner = unwrapped.inner
                if not isinstance(inner, FloatValue):
                    raise TypeError(
                        f"{op} requires floating-point operand, "
                        f"got {type(inner).__name__}")
                result_val = inner.value ** (1.0 / degree)
                result_float = mk_float(result_val, inner.width)
                unit = unwrapped.unit
                for k, v in unit.components.items():
                    if v != 0 and v % degree != 0:
                        raise TypeError(
                            f"cannot take {op} of unit "
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
                        f"cannot take {op} of unit "
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
                f"{op} requires floating-point operand, "
                f"got {type(unwrapped).__name__}")

    def _apply_operator(self, op: str, left, right):
        """Apply a binary operator to two values it has been given.

        Shared by an operator written between its operands and one
        written as a value, so `a ⧺ b` and `⧺⌿ v` mean the same thing
        by construction rather than by two implementations agreeing.
        """
        # Two plain integers meet most operators most of the time, and
        # nothing on the way to the dispatch dict concerns them: no
        # threading (rank 0), no units, no optionals.  The specials
        # (⧺, ⍳, sets, ∊, ≈) are not in _ops, so the probe misses and
        # falls through for them.
        if type(left) is IntValue and type(right) is IntValue:
            h = self._ops.get(op)
            if h is not None:
                return h(left, right)
        if op == "\N{DOUBLE PLUS}":
            return self._op_concat(left, right)
        if op == "\N{APL FUNCTIONAL SYMBOL IOTA}":
            # The container is the operand rather than a stand-in for
            # its elements, so this does not go element-wise.
            return self._op_index_of(left, right)
        if op in self._SUBSET_OPS:
            return self._op_subset(op, left, right)
        if op in self._SET_OPS:
            # Both operands are the container, as they are for ⧺, so
            # this is dispatched before anything is threaded over one.
            return self._op_set(op, left, right)
        if op == "\N{SMALL ELEMENT OF}":
            # Element-wise on the left operand only, which it does for
            # itself: the right one is the container to look through.
            return self._op_element_of(left, right)
        if op in ("=", "\N{NOT EQUAL TO}") and (isinstance(left, (SomeValue, NoneValue))
                                   or isinstance(right, (SomeValue, NoneValue))):
            # Whether there is a value at all is settled before what it
            # is, so that an optional carrying a unit is not unwrapped
            # into its unit by the dispatch below and compared as though
            # the optional had never been there.  `(v ⍳ x) == ∅` asks
            # the same question whichever way the search went.
            return self._ops[op](left, right)
        if op in ("=", "\N{NOT EQUAL TO}") \
                and (isinstance(_unwrap_operand(left), SyntaxValue)
                     or isinstance(_unwrap_operand(right), SyntaxValue)):
            # Two pieces of the program are the same where the same
            # thing is written in both, wherever each was written.
            return self._op_syntax_eq(op, _unwrap_operand(left),
                                      _unwrap_operand(right))
        if op in ("=", "\N{NOT EQUAL TO}") \
                and (_is_keyed_container(_unwrap_operand(left))
                     or _is_keyed_container(_unwrap_operand(right))):
            # A hash and a set are the operand rather than a stand-in
            # for what is in them, so they are compared whole and answer
            # one truth value rather than one for each thing in them.
            return self._op_container_eq(op, left, right)
        if op in self._LISTABLE_BINOPS:
            # An operand deeper than the operator asks for is taken
            # apart and the operator asked again of each of its
            # elements.  This sits above the unit handling below, which
            # therefore only ever meets one value at a time and keeps
            # the unit it is given.
            if value_rank(left) > 0 or value_rank(right) > 0:
                threaded = self._thread_level(
                    op, self._OPERAND_NAMES, [left, right], (0, 0),
                    lambda sub: self._apply_operator(op, sub[0], sub[1]),
                    noun="operands")
                if threaded is not None:
                    return threaded
        if op in self._APPROX_OPS:
            return self._op_approx(op, left, right)
        lu = unwrap_optional(left)
        ru = unwrap_optional(right)
        if isinstance(lu, UnitValue) or isinstance(ru, UnitValue):
            return self._unit_binop(op, lu, ru)
        return self._ops[op](left, right)

    def _op_concat(self, left, right):
        """Join two sequences: arrays at the outermost dimension, or text.

        A string and a character are both text, so joining either with
        either gives a string.  That is what builds one up a character
        at a time, and it is the same operation joining arrays does --
        the operands go together in the order they are written.

        Two dictionaries join as well, which is the one thing joining says
        that ∪ does not: what happens where both hold the same key.
        """
        lu = _unwrap_operand(left)
        ru = _unwrap_operand(right)
        if isinstance(lu, ObjectValue) and isinstance(lu.obj, HashValue) \
                or isinstance(ru, ObjectValue) \
                and isinstance(ru.obj, HashValue):
            return self._concat_hashes(lu, ru)
        for side, value in (("left", lu), ("right", ru)):
            if isinstance(value, ObjectValue) \
                    and isinstance(value.obj, SetValue):
                raise coded(2726, TypeError(
                    f"\N{DOUBLE PLUS}: the {side} operand is a set, and a set "
                    f"holds each value once -- joining two would keep "
                    f"nothing the second one repeats, which is what "
                    f"\N{UNION} answers"))
        if _joins_as_text(lu) and _joins_as_text(ru):
            return mk_str(self._text_operand(lu, "left")
                          + self._text_operand(ru, "right"))
        la = self._as_array(lu)
        ra = self._as_array(ru)
        if la is not None and ra is not None:
            # Two arrays join into one array, which holds one type of
            # value -- so they have to hold the same one.  Taking the
            # left operand's label and the right operand's values built
            # an array whose type was a lie about half of it.
            if (la.element_type is not None and ra.element_type is not None
                    and la.element_type != ra.element_type):
                raise coded(2727, TypeError(
                    f"\N{DOUBLE PLUS}: an array holds one type of value, so "
                    f"two joined hold the same one, but the left operand "
                    f"holds {la.element_type} and the right holds "
                    f"{ra.element_type}"))
            lunit = la.element_unit
            runit = ra.element_unit
            if (lunit is None) != (runit is None) or (
                    lunit is not None and not lunit.same_dimension(runit)):
                raise coded(2310, TypeError(
                    f"\N{DOUBLE PLUS}: an array holds one unit, so two "
                    f"joined hold the same one, but the left operand is "
                    f"{lunit.display_name if lunit else 'unmeasured'} and "
                    f"the right is "
                    f"{runit.display_name if runit else 'unmeasured'}"))
            etype = la.element_type or ra.element_type
            return ObjectValue(
                ArrayValue(la.values() + ra.values(), element_type=etype,
                           element_unit=lunit))
        if la is None and ra is None:
            # Neither is an array, so text is what was meant, and the
            # operand that is not text says so.
            self._text_operand(lu, "left")
            self._text_operand(ru, "right")
        if la is None:
            raise coded(2728, TypeError(
                f"\N{DOUBLE PLUS}: the left operand is "
                f"{runtime_type_of(lu)} and the right one is an array; "
                f"an array joins an array, and text joins text"))
        raise coded(2729, TypeError(
            f"\N{DOUBLE PLUS}: the left operand is an array and the right "
            f"one is {runtime_type_of(ru)}; an array joins an array, and "
            f"text joins text"))

    @staticmethod
    def _text_operand(value, side: str) -> str:
        """The text an operand of ⧺ stands for.

        A string is its text and a character is itself.  A number is
        neither: which of the two it was meant as -- the character it
        numbers, or its digits -- is not something the operator can
        decide, so the program says which.
        """
        if isinstance(value, StrValue):
            return value.value
        if isinstance(value, CharValue):
            return value.char
        raise coded(2233, TypeError(
            f"\N{DOUBLE PLUS}: the {side} operand is "
            f"{runtime_type_of(value)}, which does not go together with "
            f"text; a number becomes the character it numbers with "
            f".chr(), and its digits with std.format"))

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
            raise coded(2234, TypeError(
                f"{op_name} requires matching types, got {lu.width} and {ru.width}"))
        if isinstance(lu, FloatValue) and isinstance(ru, IntValue):
            raise coded(2235, TypeError(
                f"{op_name} requires matching types, got {lu.width} and {ru.width}"))
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

    def _thread_level(self, where: str, names, args, wants, invoke, *,
                      noun: str = "arguments", collect: bool = True,
                      fallback_type: str | None = None):
        """Take one level off whatever was handed a container.

        A position is threaded when the value is deeper than the type
        asked for: a parameter wanting one number and handed a row of
        them is handed a container of what it asked for.  What is not
        deeper is held still, so one operand may vary while the other
        does not.

        One level only.  What each element needs is decided by calling
        back into whatever called here, so a matrix is met by the same
        question its rows are and every check the caller makes is made
        again for each element rather than once for the container.

        Answers None where nothing threads, which is the ordinary case
        and costs one measurement per argument.
        """
        mapped = [i for i, arg in enumerate(args) if value_rank(arg) > wants[i]]
        if not mapped:
            return None
        arrays = {i: self._as_array(args[i]) for i in mapped}
        count = arrays[mapped[0]].sizeof
        for i in mapped[1:]:
            if arrays[i].sizeof != count:
                raise coded(2236, TypeError(
                    f"{where}: the {noun} it threads over are taken apart "
                    f"together, so they must be the same length, but "
                    f"{names[mapped[0]]} has {count} element"
                    f"{'' if count == 1 else 's'} and {names[i]} has "
                    f"{arrays[i].sizeof}"))
        results = []
        for index in range(count):
            sub = list(args)
            for i in mapped:
                sub[i] = arrays[i].get(index)
            results.append(invoke(sub))
        if not collect:
            # Nothing was answered to collect, so nothing comes back.
            return none()
        return threaded_array(results, fallback_type)

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

        # A saturating operator carries a unit the way the exact one it
        # answers to does: holding a length at the edge of its type
        # leaves it a length.  So does picking one of two lengths, which
        # is why ⌈ and ⌊ ask for their operands on the same terms: the
        # larger of a length and a duration is not a question.
        if op in ("+", "-", "\N{SQUARED PLUS}", "\N{SQUARED MINUS}",
                  "\N{LEFT CEILING}", "\N{LEFT FLOOR}"):
            if l_is_unit and not r_is_unit:
                if isinstance(r_inner, IntValue) \
                        and not is_unwidthed(r_inner.width):
                    raise coded(2311, TypeError(
                        f"cannot {op} unit {l_unit.display_name} with "
                        f"typed integer {r_inner.width} without unit"))
                op_fn = self._ops[op]
                return UnitValue(op_fn(l_inner, r_inner), l_unit)
            if r_is_unit and not l_is_unit:
                if isinstance(l_inner, IntValue) \
                        and not is_unwidthed(l_inner.width):
                    raise coded(2312, TypeError(
                        f"cannot {op} typed integer {l_inner.width} "
                        f"without unit with unit {r_unit.display_name}"))
                op_fn = self._ops[op]
                return UnitValue(op_fn(l_inner, r_inner), r_unit)
            if not l_unit.same_dimension(r_unit):
                # One side standing in for the other settles which
                # measure the answer carries; neither doing so is two
                # different things being added.
                if l_unit.stands_in_for(r_unit):
                    op_fn = self._ops[op]
                    return UnitValue(op_fn(l_inner, r_inner), r_unit)
                if r_unit.stands_in_for(l_unit):
                    op_fn = self._ops[op]
                    return UnitValue(op_fn(l_inner, r_inner), l_unit)
                raise coded(2313, TypeError(
                    f"incompatible units for {op}: "
                    f"{l_unit.display_name} and {r_unit.display_name}"))
            if l_unit == r_unit:
                op_fn = self._ops[op]
                return UnitValue(op_fn(l_inner, r_inner), l_unit)
            l_base = self._to_base_value(l_inner, l_unit)
            r_base = self._to_base_value(r_inner, r_unit)
            op_fn = self._ops[op]
            return UnitValue(op_fn(l_base, r_base), l_unit.base_form())

        if op in ("\N{MULTIPLICATION SIGN}", "\N{SQUARED TIMES}"):
            result = self._ops[op](l_inner, r_inner)
            if l_is_unit and r_is_unit:
                result_unit = l_unit * r_unit
                if result_unit.is_dimensionless():
                    return result
                return UnitValue(result, result_unit)
            return UnitValue(result, l_unit if l_is_unit else r_unit)

        if op == "\N{DIVISION SIGN}":
            result = self._ops["\N{DIVISION SIGN}"](l_inner, r_inner)
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
                if l_unit.stands_in_for(r_unit) or r_unit.stands_in_for(l_unit):
                    wanted = r_unit if l_unit.stands_in_for(r_unit) else l_unit
                    result = self._ops["%"](l_inner, r_inner)
                    if isinstance(result, ExpectedValue):
                        if not result.is_ok():
                            return result
                        result = result.ok_value
                    return UnitValue(result, wanted)
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

        if op in ("=", "\N{NOT EQUAL TO}", "<", ">", "<=", ">="):
            if l_is_unit and not r_is_unit:
                if isinstance(r_inner, IntValue) \
                        and not is_unwidthed(r_inner.width):
                    raise coded(2314, TypeError(
                        f"cannot compare unit {l_unit.display_name} with "
                        f"typed integer {r_inner.width} without unit"))
                return self._ops[op](l_inner, r_inner)
            if r_is_unit and not l_is_unit:
                if isinstance(l_inner, IntValue) \
                        and not is_unwidthed(l_inner.width):
                    raise coded(2315, TypeError(
                        f"cannot compare typed integer {l_inner.width} "
                        f"without unit with unit {r_unit.display_name}"))
                return self._ops[op](l_inner, r_inner)
            if not l_unit.same_dimension(r_unit):
                # Comparing is asking about one thing, so one side has
                # to be able to stand where the other is asked for.
                if not (l_unit.stands_in_for(r_unit)
                        or r_unit.stands_in_for(l_unit)):
                    raise coded(2316, TypeError(
                        f"incompatible units for comparison: "
                        f"{l_unit.display_name} and {r_unit.display_name}"))
                return self._ops[op](l_inner, r_inner)
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
            if value.unit.stands_in_for(target_unit):
                return UnitValue(value.inner, target_unit)
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
        raise coded(2730, TypeError(
            f"{func.name}: parameter '{param_name}' is a by-reference "
            f"mutable '{param_type}', whose length the function may change, "
            f"but the argument is a fixed-size array of {fixed} element"
            f"{'' if fixed == 1 else 's'}"))

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
            raise coded(2411, TypeError(
                f"{node.method}: cannot modify {kind} variable '{name}'"))
        if self.env.is_const_global(name):
            raise TypeError(
                f"{node.method}: cannot modify let variable '{name}'")

    def _call_container_method(self, held, name: str, args):
        """The members of a dictionary and of a set.

        What is read with [] and asked with ∊ is not repeated here: a
        member is for what those cannot say -- the keys, the values,
        and taking something out.
        """
        is_hash = isinstance(held, HashValue)
        what = "dictionary" if is_hash else "set"
        arities = {"remove": 1, "insert": 1, "clear": 0}
        if name not in arities or (name == "insert" and is_hash):
            known = ("remove, clear" if is_hash
                     else "insert, remove, clear")
            asked = ("\N{SUPERSET OF} for its keys and "
                     "\N{SUPERSET OF OR EQUAL TO} for what it holds against "
                     "them" if is_hash
                     else "\N{SUPERSET OF OR EQUAL TO} for what is in it")
            raise coded(2731, AttributeError(
                f"a {what} has no member '{name}'; it has {known}, {asked}, "
                f"is read with [] where it is a dictionary, asked with "
                f"\N{SMALL ELEMENT OF} whether something is in it, and "
                f"counted with #"))
        if len(args) != arities[name]:
            raise TypeError(
                f"{what}.{name} takes {arities[name]} argument"
                f"{'' if arities[name] == 1 else 's'}, got {len(args)}")
        if name == "clear":
            held.entries.clear()
            return none()
        wanted = unwrap_optional(args[0])
        if name == "insert":
            held.put(self._checked_key(wanted, held.value_type, None))
            return none()
        # remove: answers whether there was one to remove.
        self._checked_key(wanted, held.key_type if is_hash
                          else held.value_type, None)
        return mk_bool(held.drop(wanted))

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
            raise coded(2732, TypeError(
                f"array.{name} takes {arity} argument"
                f"{'' if arity == 1 else 's'}, got {len(args)}"))

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

    @staticmethod
    def _string_position(text: StrValue, index: Value) -> int:
        """Where in a string an index points, checked against its length.

        A string is counted in characters, so an index is a count of
        them and carries ptrdiff as an array index does -- the same
        rule, since a string is a sequence and this is a position in
        one.
        """
        from interp.units import BUILTIN_UNITS
        required = BUILTIN_UNITS["ptrdiff"]
        if isinstance(index, UnitValue):
            if not index.unit.same_dimension(required):
                raise TypeError(
                    f"string index requires unit {required.display_name}, "
                    f"got {index.unit.display_name}")
            index = index.inner
        elif isinstance(index, IntValue) and not is_unwidthed(index.width):
            raise coded(2317, TypeError(
                f"string index requires unit {required.display_name}, "
                f"got typed integer {index.width} without unit"))
        if not isinstance(index, IntValue):
            raise TypeError("string index must be an integer")
        length = len(text.value)
        if index.value < 0 or index.value >= length:
            raise coded(2733, IndexError(
                f"string index {index.value} out of range "
                f"(length {length})"))
        return index.value

    def _string_index(self, text: StrValue, index: Value):
        """The character at a position in a string."""
        return CharValue(ord(text.value[self._string_position(text, index)]))

    def _callstack_value(self, args):
        """Return the interpreted program's call stack, innermost first.

        Each entry is a (name, line, column) tuple.  The frame for the
        call to callstack itself is left out, so entry 0 is always the
        function that asked.
        """
        if args:
            raise coded(2237, TypeError("std.callstack takes no arguments"))
        frames = []
        for frame in reversed(self._call_stack):
            name, pos = frame[0], frame[1]
            line, col = (pos[0], pos[1]) if pos is not None else (0, 0)
            frames.append(TupleValue([mk_str(name), mk_int(line, "i64"),
                                      mk_int(col, "i64")]))
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
            raise coded(2817, TypeError(
                f"{struct_type.name}.offsetof: field name must be a str"))
        try:
            layout = struct_layout(struct_type, struct_lookup(self.env))
            offset = layout.offset_of(name.value)
        except LayoutError as e:
            raise coded(2818, TypeError(f"{struct_type.name}.offsetof: {e}"
                            if "no field" in str(e) else str(e)))
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
            raise coded(2819, TypeError(str(e)))
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
            # An index measured in something that stands in for the
            # array's own measure is an index: `unit tok -> ptrdiff`
            # lets a token index reach the token arrays while staying
            # something a node id is not.
            if not iu.unit.stands_in_for(required):
                raise coded(2318, TypeError(
                    f"array index requires unit {required.display_name}, "
                    f"got {iu.unit.display_name}"))
            if not isinstance(iu.inner, IntValue):
                raise TypeError("array index must be an integer")
            return iu.inner
        if isinstance(iu, IntValue):
            if is_unwidthed(iu.width):
                return iu
            raise coded(2319, TypeError(
                f"array index requires unit {required.display_name}, "
                f"got typed integer {iu.width} without unit"))
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
        pos = node.pos
        if pos is not None:
            self._last_pos = pos
            cs = self._call_stack
            if cs:
                cs[-1][1] = pos








        # Two node kinds are more than half of every expression a run
        # evaluates -- a name is forty in a hundred and a literal
        # thirteen -- and reaching their handler costs a Python frame
        # apiece.  So the plain form of each is answered here, and
        # anything the least bit unusual falls through to the handler,
        # which is where the whole of the rule still lives.  Reaching
        # into the environment's frames is the price of not calling
        # into it; the fallback below is what keeps this honest.
        # The hot cases sit first: the ladder is walked for
        # every expression, and these are most expressions.
        handler = _EXPR_DISPATCH.get(node.__class__)
        if handler is not None:
            return handler(self, node)

        if isinstance(node, WrapExpr):
            old = self._wrapping
            self._wrapping = True
            try:
                return self.eval_expr(node.expr)
            finally:
                self._wrapping = old








        # Array literal [expr, expr, ...].

        if isinstance(node, Subscript):
            # A type name with brackets after it is an array type, not
            # a subscript of anything: `i8[3]` names the type the way a
            # declaration writes it, which is what lets @typeof be
            # compared against it as it already is against `i8`.  An
            # empty dimension is part of that spelling, so this is
            # asked before an empty one is refused as an index.
            written = self._written_type(node)
            if written is not None:
                return TypeValue(written)

        if isinstance(node, Subscript) and any(i is None for i in node.indices):
            raise coded(2734, TypeError(
                "a subscript needs an index; an empty one is how an array "
                "type leaves a dimension open, which is not a value"))

        if isinstance(node, Subscript):
            val = self.eval_expr(node.obj)
            for idx_node in node.indices:
                unwrapped = unwrap_optional(val)
                if isinstance(unwrapped, ObjectValue) \
                        and isinstance(unwrapped.obj, HashValue):
                    # What is not there is not a value to invent, so
                    # the answer says whether there was one, as ⍳ does.
                    key = self.eval_expr(idx_node)
                    self._checked_key(key, unwrapped.obj.key_type, None)
                    found = unwrapped.obj.get(key)
                    val = none() if found is None else some(found)
                    continue
                if isinstance(unwrapped, ObjectValue) \
                        and isinstance(unwrapped.obj, SetValue):
                    raise coded(2735, TypeError(
                        "a set holds values rather than answering about "
                        "them by key; \N{SMALL ELEMENT OF} asks whether one "
                        "is in it"))
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
                elif isinstance(unwrapped, StrValue):
                    val = self._string_index(unwrapped, iu)
                else:
                    raise coded(2736, TypeError("multi-dimensional subscript requires nested arrays or tuples"))
            return val

        # Slice read: arr[start…end] (inclusive).












        # Subscript read: arr[i] or arr[i, j, ...] or tuple[i].
        if isinstance(node, SliceAccess):
            arr_val = self.eval_expr(node.obj)
            unwrapped = unwrap_optional(arr_val)
            if isinstance(unwrapped, StrValue):
                start = self._string_position(
                    unwrapped, unwrap_optional(self.eval_expr(node.start)))
                end = self._string_position(
                    unwrapped, unwrap_optional(self.eval_expr(node.end)))
                # Inclusive at both ends, as an array slice is.
                return mk_str(unwrapped.value[start:end + 1])
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

















        # Array allocation: new type[size] or var name : type[size] = init.
        if isinstance(node, ArrayAlloc):
            etype = node.element_type
            if etype and etype in FAST_TYPES:
                raise coded(2737, TypeError(
                    f"fast type '{etype}' cannot be used as array element type"))
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
                        raise coded(2738, TypeError(
                            f"array size mismatch: declared {declared}, "
                            f"got {format_shape(actual)}"))
                    # An empty extent takes the one the initializer had.
                    sizes = list(actual)
                    # The declared length travels with the value, so the
                    # operations that would change it can refuse.
                    if etype:
                        # Coercing against the whole written type reaches
                        # every element, however many dimensions deep.
                        return coerce_to_type(init_val,
                                              _array_type_name(etype, sizes))
                    arr = init_val.obj
                    elements = [arr.get(i) for i in range(arr.sizeof)]
                    return ObjectValue(ArrayValue(elements, element_type=etype,
                                                  fixed_size=sizes[0]))
                # One value is not an array, whatever the type says
                # the array should be, and a definition that reads as a
                # type error is one wherever it is written.  Making
                # many of one thing is what ⍴ is for, and saying so
                # leaves the making visible at the definition.
                shape = format_shape(sizes)
                if any(d is None for d in sizes):
                    # An extent the type leaves open takes its length
                    # from the initializer, and one value has none to
                    # give.
                    raise coded(2739, TypeError(
                        f"an array of {shape} is not made from one value, "
                        f"and the open dimension has nothing to take its "
                        f"extent from; write the elements out"))
                made = (f"{sizes[0]} \N{APL FUNCTIONAL SYMBOL RHO} "
                        if len(sizes) == 1
                        else f"({', '.join(str(d) for d in sizes)}) "
                             f"\N{APL FUNCTIONAL SYMBOL RHO} ")
                raise coded(2740, TypeError(
                    f"an array of {shape} is not made from one value; "
                    f"write the elements out, or make them with "
                    f"{made}<value>"))

        raise TypeError(f"unexpected expression: {type(node).__name__}")

    # ------------------------------------------------------------------
    # Statement evaluation
    # ------------------------------------------------------------------


    def _ee_IntLit(self, node):
        v = node.boxed
        if v is None:
            v = mk_int(node.value,
                       UNTYPED if node.width == "int" else node.width)
            node.boxed = v
        return v

    def _ee_FloatLit(self, node):
        return mk_float(node.value, node.width)

    def _ee_CharLit(self, node):
        return CharValue(node.code)

    def _ee_StrLit(self, node):
        return mk_str(node.text)

    def _ee_BoolLit(self, node):
        return mk_bool(node.value)

    def _ee_NoneLit(self, node):
        return none()

    def _ee_VarRef(self, node):
        if node.name == DISCARD_NAME:
            raise coded(2238, TypeError(
                "'_' discards the value assigned to it and cannot be read"))
        # Nothing is frozen in most functions, and an empty mapping says
        # so for less than a lookup in it does.
        if self._frozen_vars and self._frozen_vars.get(node.name) == "moved":
            raise TypeError(
                f"use of moved value '{node.name}'")
        # Whether it is a mutable global is a membership test on a set
        # that is nearly always empty, and being local is a lookup in a
        # frame that nearly always has it -- so the first question
        # settles almost every name, and the second is asked of the few
        # that are mutable globals rather than of every read.
        if (self._pure_func_name is not None
                and self.env.is_mutable_global(node.name)
                and not self.env.has_local(node.name)):
            raise coded(2239, TypeError(
                f"pure function '{self._pure_func_name}' cannot "
                f"read mutable global variable '{node.name}'"))
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

    def _ee_BinOp(self, node):
        pos = node.pos
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
        if node.op in ("and", "or"):
            # The spec's short-circuit pair: the right side is not
            # read when the left side already answers.  Both sides
            # are held to the logic operators' rule -- truth
            # values only.
            left = self.eval_expr(node.left)
            left_truth = self._logic_bool(_unwrap_operand(left))
            if node.op == "and" and not left_truth:
                return mk_bool(False)
            if node.op == "or" and left_truth:
                return mk_bool(True)
            right = self.eval_expr(node.right)
            if binop_pos is not None:
                self._last_pos = binop_pos
                if self._call_stack:
                    self._call_stack[-1][1] = binop_pos
            return mk_bool(self._logic_bool(_unwrap_operand(right)))
        left = self.eval_expr(node.left)
        right = self.eval_expr(node.right)
        if binop_pos is not None:
            self._last_pos = binop_pos
            if self._call_stack:
                self._call_stack[-1][1] = binop_pos
        return self._apply_operator(node.op, left, right)

    def _ee_UnaryOp(self, node):
        if node.op == "⁻" and isinstance(node.operand, IntLit):
            # A ⁻ written against an integer literal is part of the
            # literal rather than an operation on it, so ⁻128i8 is
            # the i8 whose value is ⁻128.  Read the other way the
            # positive half would have to hold it first, and the
            # lowest value of every signed type would be unwritable.
            return self._mk_int(-node.operand.value,
                                node.operand.width or "int")
        operand = self.eval_expr(node.operand)
        return self._apply_unary(node.op, operand)

    def _ee_OptSome(self, node):
        value = self.eval_expr(node.value)
        return some(value)

    def _ee_StructLit(self, node):
        return self._eval_struct_lit(node)

    def _ee_FuncCall(self, node):
        args = [self.eval_expr(a) for a in node.args]
        return self._call_func(node.name, args)

    def _dotted_name(self, node):
        """The name a chain of plain identifiers spells, or None."""
        parts = []
        n = node
        while isinstance(n, GetAttr):
            parts.append(n.attr)
            n = n.obj
        if not isinstance(n, VarRef):
            return None
        parts.append(n.name)
        parts.reverse()
        return ".".join(parts)

    def _visible_from_here(self, module: str) -> bool:
        """Whether this module hides nothing from where we are.

        A module hides nothing from itself or from what is written
        inside it; everywhere else sees only what it exports.
        """
        return module in _ancestors_of(self._cur_module)

    def _ee_MethodCall(self, node):
        # `a.b.f(…)` is a call of f in module a.b when a.b is a module.
        # It reads as a method on a.b until the name is looked at, which
        # is why the modules a program declares are known here.
        if MODULES:
            qual = self._dotted_name(node.obj)
            if qual is not None and qual in MODULES:
                full = f"{qual}.{node.method}"
                try:
                    func = self.env.lookup(full)
                except KeyError:
                    raise coded(2910, TypeError(
                        f"module '{qual}' defines no '{node.method}'")) from None
                if not getattr(func, "is_export", False) \
                        and not self._visible_from_here(qual):
                    raise coded(2911, TypeError(
                        f"'{full}' is not exported from module '{qual}'; "
                        f"@export says what a module lets others name"))
                args = [self.eval_expr(a) for a in node.args]
                return self._do_call(func, args)
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

    def _ee_GetAttr(self, node):
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
            if node.attr == "alignof":
                return self._struct_layout_attr(inst.struct_type, node.attr)
            if node.attr == "sizeof":
                raise AttributeError(_sizeof_is_gone(node.attr))
            raise AttributeError(
                f"struct '{inst.struct_type.name}' has no field '{node.attr}'")
        if isinstance(unwrapped, StructType):
            if node.attr == "alignof":
                return self._struct_layout_attr(unwrapped, node.attr)
            if node.attr == "sizeof":
                raise AttributeError(_sizeof_is_gone(node.attr))
            raise AttributeError(
                f"struct type '{unwrapped.name}' has no attribute "
                f"'{node.attr}'")
        if isinstance(unwrapped, (TupleValue, StrValue)):
            if node.attr == "sizeof":
                raise AttributeError(_sizeof_is_gone(node.attr))
        if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
            if node.attr == "sizeof":
                raise coded(2742, AttributeError(_sizeof_is_gone(node.attr)))
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
                if isinstance(attr_val, float):
                    return mk_float(attr_val)
                if isinstance(attr_val, str):
                    return mk_str(attr_val)
                return ObjectValue(attr_val)
        elif isinstance(unwrapped, IntValue):
            # int.value attribute? No, just return the int itself.
            pass
        return obj

    def _ee_ArrayLit(self, node):
        elements = [self.eval_expr(e) for e in node.elements]
        settled, unit = _literal_element_type(elements)
        if settled is not None:
            elements = [coerce_to_type(e, settled, unit, self._mk_int)
                        for e in elements]
        return ObjectValue(ArrayValue(elements, element_type=settled,
                                      element_unit=unit))

    def _ee_RangeExpr(self, node):
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

    def _ee_IfExpr(self, node):
        if to_bool(self.eval_expr(node.cond)):
            return self.eval_expr(node.then_expr)
        return self.eval_expr(node.else_expr)

    def _ee_DropUnitExpr(self, node):
        val = self.eval_expr(node.expr)
        inner = val.inner if isinstance(val, UnitValue) else val
        if not isinstance(val, UnitValue):
            self._warnings.append(
                "@dropunit: this value carries no unit to drop")
        return inner

    def _ee_RefExpr(self, node):
        bound = self.env.lookup(node.name)
        if isinstance(bound, Reference):
            # A borrow of a borrow is the same borrow.  The name is
            # already standing for somewhere else, and wrapping it again
            # would make a reference to a reference -- which reads back
            # as a reference rather than as what was lent, and would
            # leave the value one step further away at every hand-on.
            return bound
        return RefValue(self.env, node.name)

    def _ee_StaticAssert(self, node):
        for arg in node.args:
            if not _is_const_expr(arg):
                raise coded(2615, TypeError(
                    "static_assert requires compile-time constant expressions"))
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

    def _ee_StaticAssertEq(self, node):
        if not _is_const_expr(node.expected) or not _is_const_expr(node.actual):
            raise coded(2616, TypeError(
                "static_assert_eq requires compile-time constant expressions"))
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
            eq = self._unit_binop("=", eu, au)
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

    def _ee_UnitExpr(self, node):
        value = self.eval_expr(node.expr)
        from interp.units import eval_unit_formula
        unit = eval_unit_formula(node.unit_spec)
        if isinstance(value, UnitValue):
            return UnitValue(value.inner, unit)
        return UnitValue(value, unit)

    def _ee_ExpErr(self, node):
        return ExpectedValue.err(self.eval_expr(node.value))

    def _ee_TryUnwrap(self, node):
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

    def _ee_HashLit(self, node):
        keys = [self.eval_expr(k) for k, _ in node.pairs]
        values = [self.eval_expr(v) for _, v in node.pairs]
        key_type, key_unit = _literal_element_type(keys)
        value_type, value_unit = _literal_element_type(values)
        hash_value = HashValue(key_type=key_type, value_type=value_type)
        for key, value in zip(keys, values):
            key = self._checked_key(key, key_type, key_unit)
            if value_type is not None:
                value = coerce_to_type(value, value_type, value_unit,
                                       self._mk_int)
            hash_value.put(key, value)
        return ObjectValue(hash_value)

    def _ee_SetLit(self, node):
        values = [self.eval_expr(v) for v in node.elements]
        value_type, value_unit = _literal_element_type(values)
        set_value = SetValue(value_type=value_type)
        for value in values:
            set_value.put(self._checked_key(value, value_type, value_unit))
        return ObjectValue(set_value)

    def _ee_EmptyCollectionLit(self, node):
        return ObjectValue(SetValue())

    def _ee_MultiSlice(self, node):
        arr_val = self.eval_expr(node.obj)
        return self._eval_multi_slice_read(arr_val, node.specs)

    def _ee_EnumerateExpr(self, node):
        raise coded(2820, TypeError("enumerate can only be used inside foreach"))

    def _ee_TypeOfExpr(self, node):
        cached = getattr(node, "_cached_value", None)
        if cached is not None:
            return cached
        if not _is_comptime_expr(node.expr, self._comptime_vars) \
                and not self._names_a_binding(node.expr):
            raise coded(2240, TypeError(
                "@typeof requires a compile-time constant, a name, or "
                "an expression built from them"))
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

    def _ee_LimitExpr(self, node):
        return self._eval_limit(node)

    def _ee_Quote(self, node):
        return self._eval_quote(node)

    def _ee_Reflect(self, node):
        import copy as _copy
        return SyntaxValue(node=_copy.deepcopy(node.tree))

    def _ee_Splice(self, node):
        raise TypeError(
            "$ puts a value into a piece of program, and there is no "
            "piece of program here")

    def _ee_SizeOfExpr(self, node):
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
        result = self._memory_size(unwrap_optional(val))
        if _is_const_expr(node.expr):
            node._cached_value = result
        return result

    def _ee_ResultOfExpr(self, node):
        cached = getattr(node, "_cached_value", None)
        if cached is not None:
            return cached
        try:
            func = self.env.lookup(node.name)
        except KeyError:
            raise coded(2110, TypeError(f"@resultof: unknown function '{node.name}'"))
        if isinstance(func, FuncValue):
            # Every parsed signature records a return type, ∅ where
            # none was written, so there is nothing to fall back to.
            result = TypeValue(func.ret_type)
        elif isinstance(func, BuiltinFunc):
            result = TypeValue("builtin")
        else:
            raise TypeError(f"@resultof: '{node.name}' is not a function")
        node._cached_value = result
        return result

    def _ee_UnitOfExpr(self, node):
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

    def _ee_UnitRefExpr(self, node):
        from interp.units import eval_unit_formula
        unit = eval_unit_formula(node.unit_spec)
        return UnitOfValue(unit)

    def _ee_LambdaExpr(self, node):
        return self._eval_lambda_expr(node)

    def _ee_TupleLit(self, node):
        elements = [self.eval_expr(e) for e in node.elements]
        if len(elements) > 1 and all(isinstance(e, TypeValue)
                                     for e in elements):
            # A name that names a type is that type wherever it is
            # written, and a tuple of them is the tuple type they
            # describe, so a program compares against `(i64, str)`
            # rather than against the text of it.
            return TypeValue("(" + ", ".join(e.name for e in elements) + ")")
        return TupleValue(elements)

    def _ee_OperatorRef(self, node):
        return BuiltinFunc(
            node.op, 2,
            lambda args, op=node.op: self._apply_operator(op, args[0],
                                                          args[1]))

    def _ee_FoldExpr(self, node):
        return self._eval_fold(node)

    def _ee_MapExpr(self, node):
        return self._eval_map(node)

    def _ee_ReshapeExpr(self, node):
        shape = self.eval_expr(node.shape)
        data = self.eval_expr(node.data)
        return self._eval_reshape(shape, data)

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
        last = len(stmts) - 1
        for i, stmt in enumerate(stmts):
            result = self.eval_stmt(stmt)
            if isinstance(result, _ReturnSentinel):
                raise result
            if (i != last and isinstance(stmt, ExprStmt)
                    and isinstance(result, LambdaValue)):
                self._warn_discarded_lambda(result)
        return result

    def eval_stmt(self, stmt):
        """Evaluate a single statement, releasing what it does not keep.

        Resources produced while the statement runs but neither bound to
        a name nor handed back as its value are released as it finishes.

        Returns:
            The last computed value, or a _ReturnSentinel for return statements.
        """
        # Only a value holding an operating system resource is ever
        # registered here, and a statement almost never produces one, so
        # the list is not built until something needs it: _NO_TEMPS says
        # "registration is on and nothing has come" without allocating.
        outer = self._temporaries
        self._temporaries = _NO_TEMPS
        try:
            result = self._eval_stmt(stmt)
            if self._temporaries:
                self._release_temporaries(result)
            return result
        except BaseException:
            if self._temporaries:
                self._release_temporaries(None)
            raise
        finally:
            self._temporaries = outer

    def _watchdog_tick(self):
        """Count a statement; every few thousand, look at the clock."""
        global _watchdog_steps, _watchdog_countdown, _watchdog_next_beat
        _watchdog_steps += 1
        _watchdog_countdown -= 1
        if _watchdog_countdown > 0:
            return
        _watchdog_countdown = _WATCHDOG_CHECK_EVERY
        now = _time.monotonic()
        if _watchdog_beat_every and now >= _watchdog_next_beat:
            _watchdog_next_beat = now + _watchdog_beat_every
            where = ""
            if self._call_stack:
                chain = " → ".join(f[0] for f in self._call_stack[-4:])
                pos = self._call_stack[-1][1]
                if pos is not None:
                    where = f", in {chain} at line {pos[0]}"
                else:
                    where = f", in {chain}"
            done = ""
            if _fn_calls_done:
                done = (f", {_fn_calls_done:,} calls"
                        f" (last finished: {_fn_last_name})")
            print(f"interp: {now - _watchdog_started:.0f}s, "
                  f"{_watchdog_steps:,} statements{done}{where}",
                  file=_sys.stderr, flush=True)
        if _watchdog_deadline is not None and now >= _watchdog_deadline:
            if _fn_stats_on:
                report_fn_stats()
            raise NoForwardProgress(
                f"no result within the time limit: "
                f"{_watchdog_steps:,} statements over "
                f"{now - _watchdog_started:.0f}s; the run was stopped "
                f"where it stood (raise --timeout if it was only slow)")

    def _eval_stmt(self, stmt):
        """Evaluate a single statement.

        Returns:
            The last computed value, or a _ReturnSentinel for return statements.
        """
        if _watchdog_armed:
            self._watchdog_tick()
        pos = getattr(stmt, "pos", None)
        if pos is not None:
            self._last_pos = pos
            cs = self._call_stack
            if cs:
                cs[-1][1] = pos


        handler = _STMT_DISPATCH.get(stmt.__class__)
        if handler is not None:
            return handler(self, stmt)

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
            # Left to right.  What is written stands to the left of the
            # value, so the target's own subexpressions -- the thing
            # being written into, and where in it -- are evaluated
            # before the value is.  Held here so the code below reads
            # them rather than evaluating them a second time, which
            # would run their effects twice.
            _pre_obj = _MISSING
            _pre_idx = None
            _pre_start = _pre_end = _MISSING
            if isinstance(target_ast, (MultiSlice, SliceAccess, Subscript,
                                       GetAttr)):
                _pre_obj = self.eval_expr(target_ast.obj)
                if isinstance(target_ast, SliceAccess):
                    _pre_start = self.eval_expr(target_ast.start)
                    _pre_end = self.eval_expr(target_ast.end)
                elif isinstance(target_ast, Subscript):
                    _pre_idx = [self.eval_expr(i)
                                for i in target_ast.indices]
            rhs = self.eval_expr(rhs_ast)
            if isinstance(target_ast, VarRef):
                self._check_assigned_kind(target_ast.name, rhs)
            if isinstance(target_ast, MultiSlice):
                # arr[range, range, ...] ← matrix — multi-dim slice write.
                arr_val = _pre_obj
                self._eval_multi_slice_write(arr_val, target_ast.specs, rhs)
            elif isinstance(target_ast, SliceAccess):
                # arr[s…e] ← rhs_array — copy elements into slice.
                arr_val = _pre_obj
                au = unwrap_optional(arr_val)
                if isinstance(au, ObjectValue) and isinstance(au.obj, ArrayValue):
                    s = unwrap_optional(_pre_start)
                    e = unwrap_optional(_pre_end)
                    s = self._check_index_unit(s, au.obj)
                    e = self._check_index_unit(e, au.obj)
                    rhs_arr = self._as_array(rhs)
                    if rhs_arr is not None:
                        for i in range(rhs_arr.sizeof):
                            au.obj.set(s.value + i, rhs_arr.get(i))
            elif isinstance(target_ast, Subscript):
                # arr[i] or arr[i, j, ...] ← value — mutate (nested) array element.
                val = _pre_obj
                for _i, idx_node in enumerate(target_ast.indices[:-1]):
                    unwrapped = unwrap_optional(val)
                    idx_val = _pre_idx[_i]
                    iu = unwrap_optional(idx_val)
                    if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
                        iu = self._check_index_unit(iu, unwrapped.obj)
                        val = unwrapped.obj.get(iu.value)
                    else:
                        raise TypeError("multi-dimensional subscript requires nested arrays")
                last_idx_node = target_ast.indices[-1]
                unwrapped = unwrap_optional(val)
                if isinstance(unwrapped, StrValue):
                    # A string is read at a position, not written at
                    # one: a character may be a different width in
                    # UTF-8 than the one it replaces, so there is no
                    # writing in place to be had.  A new string is
                    # built instead.
                    raise coded(2745, TypeError(
                        "a string cannot be written through; build the "
                        "string that is wanted, joining with \N{DOUBLE PLUS}"))
                if isinstance(unwrapped, ObjectValue) \
                        and isinstance(unwrapped.obj, HashValue):
                    # Writing at a key puts it there, whether or not it
                    # was there before: a dictionary has no length to run past
                    # and nothing to be out of range of.
                    hv = unwrapped.obj
                    key = self._checked_key(_pre_idx[-1], hv.key_type, None)
                    value = rhs
                    if hv.value_type is not None:
                        value = coerce_to_type(value, hv.value_type)
                    elif hv.sizeof:
                        held = runtime_type_of(hv.values()[0])
                        mismatch = _scalar_kind_mismatch(value, held)
                        if mismatch is not None:
                            raise TypeError(
                                f"a dictionary of {held} cannot hold {mismatch}")
                    hv.put(key, value)
                elif isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
                    iu = unwrap_optional(_pre_idx[-1])
                    iu = self._check_index_unit(iu, unwrapped.obj)
                    unwrapped.obj.set(iu.value, rhs)
                else:
                    raise TypeError(
                        f"cannot write through a subscript of "
                        f"{runtime_type_of(unwrapped)}")
            elif isinstance(target_ast, GetAttr):
                obj_val = _pre_obj
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
                        funit = inst.struct_type.field_unit(target_ast.attr)
                        if funit is not None:
                            rhs = coerce_to_type(rhs, field_type, funit,
                                                 self._mk_int)
                        else:
                            rhs = coerce_arg(rhs, field_type,
                                             "field assignment",
                                             target_ast.attr)
                    inst.field_values[target_ast.attr] = rhs
                elif isinstance(au, ObjectValue) and au.obj is std \
                        and target_ast.attr in _STD_SETTINGS:
                    setting = unwrap_optional(rhs)
                    if not isinstance(setting, (FloatValue, IntValue)):
                        raise TypeError(
                            f"std.{target_ast.attr} is a number, but the "
                            f"value is {self._value_type_name(setting)}")
                    setattr(std, target_ast.attr, float(setting.value))
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
                        raise coded(2412, TypeError(
                            f"cannot assign to {kind} variable "
                            f"'{target_ast.name}'"))
                if self.env.is_const_global(target_ast.name):
                    raise coded(2241, TypeError(
                        f"cannot assign to let variable "
                        f"'{target_ast.name}'"))
                if (self._pure_func_name is not None
                        and not self.env.has_local(target_ast.name)):
                    raise coded(2242, TypeError(
                        f"pure function '{self._pure_func_name}' cannot "
                        f"assign to non-local variable '{target_ast.name}'"))
                current = self.env.lookup(target_ast.name)
                if isinstance(current, Reference):
                    current.set(rhs)
                    return none()
                decl = self.env.declaration(target_ast.name)
                if decl is not None and not decl.says_nothing():
                    rhs = self._coerce_declared(rhs, decl, target_ast.name)
                elif isinstance(current, UnitValue):
                    # Nothing was written down, so what the name holds
                    # is all there is to go on.
                    if isinstance(rhs, UnitValue):
                        rhs = self._convert_unit_value(rhs, current.unit)
                    else:
                        raise TypeError(
                            f"cannot assign dimensionless value to "
                            f"'{target_ast.name}' which has unit "
                            f"{current.unit.display_name}")
                # The value is stored on its own: what the definition
                # said outlives it.
                if not self.env.update(target_ast.name, rhs):
                    self.env.define(target_ast.name, rhs)
            return none()









        if isinstance(stmt, (BreakStmt, ContinueStmt)):
            word = "break" if isinstance(stmt, BreakStmt) else "continue"
            # The static checks catch this in a function; what reaches
            # here is written somewhere they do not read, such as a
            # statement typed at the prompt.
            if not self._loops:
                raise TypeError(f"{word} is written outside any loop, so "
                                f"there is no loop for it to act on")
            if stmt.label is not None and stmt.label not in self._loops:
                raise TypeError(f"{word} names the loop "
                                f"'{stmt.label}', which is not one it is "
                                f"inside")
            if isinstance(stmt, BreakStmt):
                raise _BreakSignal(stmt.label)
            raise _ContinueSignal(stmt.label)




        return none()


    def _es_ExpectStmt(self, stmt):
        return self._eval_expect(stmt)

    def _es_VarDef(self, stmt):
        if stmt.type_annotation is not None:
            check_bootstrap_type(stmt.type_annotation,
                                 f"'{stmt.name}'")
        if is_type_name(stmt.name):
            raise coded(2243, TypeError(
                f"'{stmt.name}' names a type and cannot name a variable"))
        if stmt.name == DISCARD_NAME:
            # `let _ := expr` discards too, so that a value can be
            # thrown away without inventing a name for it.
            self.eval_expr(stmt.init_expr)
            return none()
        if stmt.name in self._frozen_vars:
            kind = self._frozen_vars[stmt.name]
            if kind == "foreach":
                from interp.errors import Diagnostic
                self._warnings.append(Diagnostic(
                    f"redefinition of foreach variable '{stmt.name}'", 2420))
            elif not stmt.is_const:
                raise coded(2244, TypeError(
                    f"cannot redefine {kind} variable '{stmt.name}'"))
        value = self.eval_expr(stmt.init_expr)
        if stmt.type_annotation is None:
            # Naming a value settles it, and without a type written
            # down a number settles on `int` or `float` -- neither
            # of which the bootstrap provides.
            check_binding_settles(value, stmt.name)
            check_bootstrap_binding(value, stmt.name)
            value = settle_untyped(value)
        unit = None
        if stmt.unit_spec is not None:
            from interp.units import eval_unit_formula
            unit = eval_unit_formula(stmt.unit_spec)
        if stmt.type_annotation is not None \
                and not isinstance(stmt.init_expr, ArrayAlloc):
            # An array declaration writes its shape in brackets that
            # the annotation does not carry, and the allocation has
            # already measured the value against the whole of it.
            # Coercing again here would meet the element type alone
            # and take an array for it.
            ann = stmt.type_annotation
            if self._generic_map and is_generic_type(ann):
                ann = _substitute_generics(ann, self._generic_map)
            # The binding states a unit as well as a type, so the
            # type is what each number is held in and the unit is
            # what it counts.  For an array that means the
            # elements: a unit around the container is a value
            # nothing can read an element out of.
            value = coerce_to_type(value, ann, unit, self._mk_int)
        else:
            # An allocation has already measured the value against
            # the whole of its type, so only the unit is left.
            value = apply_unit(value, unit, self._mk_int)
        self.env.define(stmt.name, value,
                        Decl(self._declared_type_of(stmt, value), unit))
        if not self._bind_reshape_access(stmt):
            if stmt.is_const:
                self._frozen_vars[stmt.name] = "let"
        return none()

    def _es_DestructureDef(self, stmt):
        return self._eval_destructure(stmt)

    def _es_SumTypeDef(self, stmt):
        register_sum_type(stmt.name, stmt.alternatives)
        return none()

    def _es_TypeDef(self, stmt):
        target = stmt.target
        if self._generic_map and is_generic_type(target):
            target = _substitute_generics(target, self._generic_map)
        register_type_alias(stmt.name, target)
        return none()

    def _es_ExprStmt(self, stmt):
        return self.eval_expr(stmt.expr)

    def _warn_discarded_lambda(self, value):
        """Report a lambda that a statement computed and then dropped.

        The spec promises this catches accidental partial applications.
        The trailing statement of a body is not reported here: its value
        may be the function's answer, and the static analysis already
        weighs that case against the return type.
        """
        message = "lambda value is not used (not assigned or returned)"
        if value.partial_func is not None:
            n = len(value.params)
            message += (
                f"; the call answered a partial application of "
                f"'{value.partial_func.name}' that still waits for "
                f"{n} argument{'s' if n != 1 else ''}")
        self._warnings.append(message)
        if not self._collect_warnings:
            from interp.errors import diagnostic_level
            level = diagnostic_level("warning")
            if level == "error":
                raise TypeError(message)
            print(f"{level}: {message}", file=_sys.stderr)

    def _es_IfStmt(self, stmt):
        return self._eval_if(stmt)

    def _es_WhileStmt(self, stmt):
        return self._eval_while(stmt)

    def _es_ForEachStmt(self, stmt):
        return self._eval_foreach(stmt)

    def _es_MatchStmt(self, stmt):
        return self._eval_match(stmt)

    def _es_CatchStmt(self, stmt):
        return self._eval_catch(stmt)

    def _es_ReturnStmt(self, stmt):
        if stmt.value is not None:
            value = self.eval_expr(stmt.value)
        else:
            value = none()
        raise _ReturnSentinel(value)

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
                raise coded(2413, TypeError(
                    f"cannot take a mutable view of {kind} variable '{name}'"))
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
            raise coded(2746, TypeError(f"'{name}' holds {held} and cannot take {mismatch}"))

    @staticmethod
    def _declared_type_of(stmt, value) -> str | None:
        """The type a definition stated, brackets and all.

        An allocation keeps its shape in the brackets rather than in
        the annotation -- `let h : u32[8]` states `u32` and allocates 8
        -- so the two halves are put back together here.  A dimension
        the definition left for the initializer to decide stays open,
        since what it settled on is this value's length rather than
        something the name holds to.
        """
        ann = stmt.type_annotation
        if ann is None or not isinstance(stmt.init_expr, ArrayAlloc):
            return ann
        alloc = stmt.init_expr
        written = [alloc.size_expr, *alloc.rest_dims]
        inner = unwrap_optional(value)
        if not (isinstance(inner, ObjectValue)
                and isinstance(inner.obj, ArrayValue)):
            return ann
        extents = array_shape(inner.obj)
        dims = [None if written[i] is None else extents[i]
                for i in range(min(len(written), len(extents)))]
        return _array_type_name(ann, dims)

    @staticmethod
    def _carried_unit(value: Value):
        """What a value measures, or None where it measures nothing.

        An array answers for its elements, since that is where a unit
        sits.  An empty one answers for the declaration rather than
        against it: there is nothing in it to disagree.
        """
        inner = unwrap_optional(value)
        if isinstance(inner, UnitValue):
            return inner.unit
        if isinstance(inner, ObjectValue) and isinstance(inner.obj, ArrayValue):
            if inner.obj.sizeof == 0:
                return inner.obj.element_unit or _EMPTY_MEASURE
            return Evaluator._carried_unit(inner.obj.get(0))
        return None

    def _coerce_declared(self, value: Value, decl, name: str) -> Value:
        """Measure an assigned value against what the definition said.

        The definition is what a name holds to, not the value it holds
        at the moment: a binding that has been assigned once would
        otherwise answer for what it was last given rather than for
        what it was declared, and a declaration would last exactly one
        statement.
        """
        if decl.type_name is not None:
            # Said first and in the definition's own words, since a
            # kind that does not fit is a plainer thing to be told than
            # whatever the conversion below would say about it.
            held = resolve_type_alias(decl.type_name)
            mismatch = _scalar_kind_mismatch(unwrap_optional(value), held)
            if mismatch is not None:
                raise TypeError(
                    f"'{name}' holds {held} and cannot take {mismatch}")
        if decl.unit is None and isinstance(unwrap_optional(value), UnitValue):
            raise coded(2321, TypeError(
                f"'{name}' carries no unit, but the value is "
                f"{unwrap_optional(value).unit.display_name}; "
                f"use @dropunit to part with it"))
        if decl.unit is not None and self._carried_unit(value) is None:
            # A definition may measure a bare number, since it is the
            # definition that says what the number counts.  An
            # assignment says nothing, so what it stores has to arrive
            # measured or the measure would be invented for it.
            raise coded(2322, TypeError(
                f"cannot assign dimensionless value to '{name}' which has "
                f"unit {decl.unit.display_name}"))
        if decl.type_name is None:
            return apply_unit(value, decl.unit)
        ann = decl.type_name
        if self._generic_map and is_generic_type(ann):
            ann = _substitute_generics(ann, self._generic_map)
        return coerce_to_type(value, ann, unit=decl.unit)

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
            raise coded(2414, TypeError(
                f"cannot assign to {part} of {kind} variable '{name}'"))
        if self.env.is_const_global(name):
            raise coded(2747, TypeError(
                f"cannot assign to {part} of let variable '{name}'"))

    @staticmethod
    def _is_mine(signal, node) -> bool:
        """Whether a loop signal is for this loop.

        One with no label belongs to the loop it sits directly inside;
        one with a label belongs to the loop of that name, and travels
        outward through the loops in between.
        """
        return signal.label is None or signal.label == node.label

    def _run_loop_body(self, body, node) -> bool:
        """Run one turn of a loop.  False where the loop should stop."""
        self._loops.append(node.label)
        try:
            self.eval_stmts(body)
        except _ContinueSignal as signal:
            if not self._is_mine(signal, node):
                raise
        except _BreakSignal as signal:
            if not self._is_mine(signal, node):
                raise
            return False
        finally:
            self._loops.pop()
        return True

    def _eval_while(self, node: WhileStmt):
        """Evaluate a while loop, with or without a bound variable."""
        if node.var_name is None:
            while to_bool(self.eval_expr(node.cond)):
                if not self._run_loop_body(node.body, node):
                    break
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
                        raise coded(2245, TypeError(
                            f"'{name}' is declared mut, but the loop produces "
                            f"values that cannot be written back"))
                elif isinstance(bound, Reference):
                    # A plain binding names the value, not the place it
                    # came from, so it holds a copy and its type is the
                    # element's own.
                    bound = bound.get()
                if node.var_type is not None and not isinstance(bound, Reference):
                    bound = coerce_to_type(bound, node.var_type)
                self.env.define(name, bound)
                if not self._run_loop_body(node.body, node):
                    break
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
                    TupleValue([mk_int(i, "i64"), v])
                    for i, v in enumerate(inner)
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
                # The loop variable is held in what the bounds settle
                # on.  Where they settle on nothing it is uncommitted,
                # as a literal is, rather than the arbitrary-precision
                # int the bootstrap does not have: it settles at the
                # first typed thing it meets, and an index is one of
                # the places that reads it.
                elem_width = resolve_width(s.width, e.width)
                if is_unwidthed(elem_width):
                    elem_width = UNTYPED
                mk_val = ((lambda i: UnitValue(mk_int(i, elem_width), range_unit))
                          if range_unit is not None
                          else (lambda i: mk_int(i, elem_width)))
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
                        from interp.errors import ProgramStop
                        raise ProgramStop("range step must not be zero")
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
                raise coded(2246, TypeError(
                    f"'{var_name}' names a type and cannot name a "
                    f"loop variable"))

        if any(borrows) and (destructure or num_vars != num_iters):
            raise coded(2415, TypeError(
                "foreach over a borrow needs one variable per borrowed "
                "container"))

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

        flat_names = []
        for name in var_names:
            flat_names.extend(_flatten_names(name))
        for name, kind in zip(var_names, freeze_kinds):
            if kind is not None:
                for one in _flatten_names(name):
                    self._frozen_vars[one] = kind
        self._comptime_vars |= set(flat_names)
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
                        if isinstance(var_name, tuple):
                            # The name is a pattern, so what arrives is
                            # taken apart into the names it holds.
                            self._bind_parameter_names(
                                var_name, val, self.env, "foreach")
                            continue
                        # A reference is bound as-is; coercing it would
                        # replace it with a copy of the element.
                        if var_type is not None and not isinstance(val, Reference):
                            val = coerce_to_type(val, var_type)
                        self.env.define(var_name, val)
                if not self._run_loop_body(node.body, node):
                    break
        finally:
            for name in flat_names:
                self._frozen_vars.pop(name, None)
            self._comptime_vars -= set(flat_names)
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
                raise coded(2416, TypeError(
                    f"cannot mutably borrow {frozen} variable '{name}'"))
            if self.env.is_const_global(name):
                raise TypeError(
                    f"cannot mutably borrow let variable '{name}'")

        val = unwrap_optional(self.eval_expr(expr.expr))
        if not (isinstance(val, ObjectValue)
                and isinstance(val.obj, ArrayValue)):
            kind = "&mut" if expr.is_mut else "&"
            raise coded(2417, TypeError(
                f"foreach over {kind} requires an array, got "
                f"{self._value_type_name(val)}"))
        array = val.obj
        return [ElementRef(array, i, expr.is_mut)
                for i in range(array.sizeof)]

    def _resolve_iterable(self, expr, is_comptime: bool = False) -> list[Value]:
        """Resolve an expression to a list of values for foreach iteration."""
        val = unwrap_optional(self.eval_expr(expr))
        if isinstance(val, RangeValue):
            return [mk_int(i) for i in val.to_list()]
        if isinstance(val, ObjectValue) and isinstance(val.obj, ArrayValue):
            arr = val.obj
            if arr._backing is None:
                # the live list, not a copy: walking a large array is
                # most of what large programs do, and the copy cost the
                # array's length at every loop
                return arr.elements
            return arr.values()
        if isinstance(val, ObjectValue) and isinstance(val.obj, HashValue):
            # An entry is its key and what is held against it, which is
            # a pair -- so `foreach (k, v) := d` names both halves the
            # way any tuple is taken apart.
            return [TupleValue([k, v]) for k, v in val.obj.pairs()]
        if isinstance(val, ObjectValue) and isinstance(val.obj, SetValue):
            return val.obj.values()
        if isinstance(val, StrValue):
            # A string is made of characters, so that is what iterating
            # one hands over -- not strings of one, which would make
            # every element a container of itself.
            return [CharValue(ord(c)) for c in val.value]
        if is_comptime and isinstance(val, TupleValue):
            return list(val.elements)
        raise TypeError(
            f"foreach requires range or iterable, got {type(val).__name__}")

    def _eval_destructure(self, stmt: DestructureDef):
        """Bind one name to each element of a tuple.

        The annotation, where there is one, is the tuple's, so it
        settles the elements before they are named and each name takes
        the type of its own position.
        """
        value = self.eval_expr(stmt.init_expr)
        if stmt.type_annotation is not None:
            value = coerce_to_type(value, stmt.type_annotation)
        self._bind_destructured(stmt.names, value, stmt)
        return none()

    def _bind_parameter_names(self, names, value, call_env, func_name: str):
        """Bind each name of a destructured parameter to its element."""
        inner = unwrap_optional(value)
        if not isinstance(inner, TupleValue):
            raise TypeError(
                f"{func_name}: parameter {_names_display(names)} names the "
                f"elements of a tuple, but the argument is "
                f"{runtime_type_of(inner)}")
        if len(inner.elements) != len(names):
            raise TypeError(
                f"{func_name}: parameter {_names_display(names)} names "
                f"{len(names)} elements, but the argument has "
                f"{len(inner.elements)}")
        for name, element in zip(names, inner.elements):
            if isinstance(name, tuple):
                self._bind_parameter_names(name, element, call_env, func_name)
                continue
            if name == DISCARD_NAME:
                continue
            call_env.define(name, settle_untyped(element))

    def _bind_destructured(self, names, value, stmt: DestructureDef):
        """Bind each name to its element, taking nested tuples apart."""
        inner = unwrap_optional(value)
        if not isinstance(inner, TupleValue):
            raise coded(2821, TypeError(
                f"a definition taking a tuple apart needs a tuple, but the "
                f"value is {runtime_type_of(inner)}"))
        if len(inner.elements) != len(names):
            raise coded(2822, TypeError(
                f"the definition names {len(names)} elements, but the "
                f"tuple has {len(inner.elements)}"))
        for name, element in zip(names, inner.elements):
            if isinstance(name, list):
                self._bind_destructured(name, element, stmt)
                continue
            if name == DISCARD_NAME:
                continue
            if is_type_name(name):
                raise TypeError(
                    f"'{name}' names a type and cannot name a variable")
            if stmt.type_annotation is None:
                check_bootstrap_binding(element, name)
            self.env.define(name, settle_untyped(element))
            if stmt.is_const:
                self._frozen_vars[name] = "let"

    def _eval_expect(self, node: ExpectStmt):
        """Evaluate a statement wrapped in @expect annotations.

        Captures errors and warnings produced by the inner statement and
        matches them against the expected patterns.  Raises TypeError if
        any expectation remains unmatched.
        """
        diagnostics: list[tuple[str, str]] = []
        # Diagnostics found before the program ran, about this statement.
        diagnostics.extend(
            ("warning", w) for w in getattr(node.stmt, "static_warnings", ()))
        diagnostics.extend(
            ("error", e) for e in getattr(node.stmt, "static_errors", ()))
        saved_warnings = self._warnings
        saved_collect = self._collect_warnings
        self._warnings = []
        self._collect_warnings = True
        try:
            self.eval_stmt(node.stmt)
        except Exception as e:
            from interp.errors import Diagnostic
            diagnostics.append(
                ("error", Diagnostic(str(e), getattr(e, "diag_code", None))))
        diagnostics.extend(("warning", w) for w in self._warnings)
        self._warnings = saved_warnings
        self._collect_warnings = saved_collect

        remaining = list(node.expectations)
        for level, msg in diagnostics:
            for i, exp in enumerate(remaining):
                exp_level, exp_pattern, exp_code, exp_line = exp
                # -Werror makes a warning an error, on both sides: an
                # @expect written for one still accounts for it.
                if diagnostic_level(level) != diagnostic_level(exp_level):
                    continue
                if exp_code is not None:
                    if getattr(msg, "code", None) != exp_code:
                        continue
                    if exp_pattern is not None and str(msg) != exp_pattern:
                        from interp.errors import (
                            _record_expect_drift, source_path_in_hand)
                        _record_expect_drift(source_path_in_hand(), exp_line,
                                             exp_code, exp_pattern, str(msg))
                elif not re.search(exp_pattern, msg):
                    continue
                elif __import__("os").environ.get("NGPL_EXPECT_SITES"):
                    import json
                    from interp.errors import source_path_in_hand
                    with open(__import__("os").environ["NGPL_EXPECT_SITES"],
                              "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(
                            {"expect_file": source_path_in_hand(),
                             "expect_line": exp_line,
                             "pattern": exp_pattern, "message": str(msg),
                             "code": getattr(msg, "code", None)}) + "\n")
                remaining.pop(i)
                break

        if remaining:
            unmatched = "; ".join(
                (f"@expect {lv} {code}" if code is not None
                 else f"@expect {lv} \"{pat}\"")
                for lv, pat, code, _ln in remaining)
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

        # An enumeration is matched by naming a value of it.
        if any(arm.kind == "enum" for arm in node.arms):
            return self._eval_match_by_enum(node, subject)

        shape, inner = self._match_shape(subject)

        for arm in node.arms:
            if arm.kind == "wildcard":
                return self.eval_stmts(arm.body)
            if arm.kind != shape:
                continue
            if arm.kind == "none":
                return self.eval_stmts(arm.body)
            # ∃(name) or ∄(name), both of which bind.
            return self._eval_bound_arm(arm, inner)

        described = {"some": "a present value",
                     "none": "\N{EMPTY SET}",
                     "err": "a failed result"}[shape]
        raise coded(2247, TypeError(
            f"match has no arm for {described}; add the missing pattern "
            f"or a _ arm"))

    def _eval_match_by_enum(self, node: MatchStmt, subject):
        """Dispatch on which value of an enumeration the subject is.

        An enumerator holds nothing beside which one it is, so an arm
        binds nothing.  Which arms there must be is settled before the
        program runs -- see _static_match_check -- so reaching the end
        here means the subject was not a value the enumeration has,
        which a number admitted into an enum-typed binding cannot be.
        """
        from interp.value import EnumValue
        val = unwrap_optional(subject)
        if not isinstance(val, EnumValue):
            raise coded(2248, TypeError(
                f"match names values of an enumeration, but the subject "
                f"is {runtime_type_of(val)}"))
        wildcard = None
        for arm in node.arms:
            if arm.kind == "wildcard":
                wildcard = wildcard if wildcard is not None else arm
                continue
            if arm.kind != "enum":
                continue
            if arm.type_name != val.enum_type.name:
                raise coded(2249, TypeError(
                    f"the subject is {val.enum_type.name} and this arm "
                    f"names {arm.type_name}.{arm.member}"))
            if val.enum_type.members.get(arm.member) == val.value:
                return self.eval_stmts(arm.body)
        if wildcard is not None:
            return self.eval_stmts(wildcard.body)
        shown = val.enum_type.values_to_names.get(val.value, str(val.value))
        raise coded(2250, TypeError(
            f"match has no arm for {val.enum_type.name}.{shown}; add the "
            f"missing pattern or a _ arm"))

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
                if index is None:
                    dims.append("")
                elif isinstance(index, IntLit):
                    dims.append(str(index.value))
                else:
                    return None
            return f"{expr.obj.name}[{','.join(dims)}]"
        return None

    def _eval_limit(self, node):
        """The extreme value a numeric type can hold.

        The operand may name the type or name something of it, since
        the question is about the type either way.
        """
        written = self._written_type(node.expr)
        if written is not None:
            type_name = written
        elif self._names_a_binding(node.expr):
            type_name = runtime_type_of(
                unwrap_optional(self.eval_expr(node.expr)))
        else:
            raise TypeError(
                f"@{node.kind} requires a numeric type, a name, or an "
                f"expression built from them")

        resolved = resolve_type_alias(type_name)
        bounds = int_limits(resolved)
        if bounds is not None:
            low, high = bounds
            return mk_int(low if node.kind == "min" else high, resolved)
        bounds = float_limits(resolved)
        if bounds is not None:
            low, high = bounds
            return mk_float(low if node.kind == "min" else high, resolved)
        if resolved in ("int", "float"):
            raise TypeError(
                f"@{node.kind}: '{resolved}' is arbitrary-precision and has "
                f"no {'smallest' if node.kind == 'min' else 'largest'} value")
        raise coded(2248, TypeError(
            f"@{node.kind}: '{type_name}' is not a numeric type"))

    def _memory_size(self, value):
        """How much memory a value takes, in bytes.

        One question with one answer, whatever it is asked about.  It
        used to be two: a scalar answered what it occupied and a
        container answered how many things were in it, in the same
        word.  How many is # now, and this measures.
        """
        from interp.units import BUILTIN_UNITS
        if isinstance(value, ObjectValue) and isinstance(value.obj, ArrayValue):
            arr = value.obj
            total = 0
            for index in range(arr.sizeof):
                inner = self._memory_size(unwrap_optional(arr.get(index)))
                total += inner.inner.value
            return UnitValue(mk_int(total), BUILTIN_UNITS["byte"])
        if isinstance(value, TupleValue):
            total = 0
            for element in value.elements:
                inner = self._memory_size(unwrap_optional(element))
                total += inner.inner.value
            return UnitValue(mk_int(total), BUILTIN_UNITS["byte"])
        if isinstance(value, StrValue):
            # What it takes to hold the text, which is what it is
            # encoded as rather than how many characters that is.
            return UnitValue(mk_int(len(value.value.encode("utf-8"))),
                             BUILTIN_UNITS["byte"])
        if isinstance(value, ObjectValue) \
                and isinstance(value.obj, StructInstance):
            return self._struct_layout_attr(value.obj.struct_type, "sizeof")
        if isinstance(value, StructType):
            return self._struct_layout_attr(value, "sizeof")
        if isinstance(value, UnitValue):
            return self._memory_size(value.inner)
        return self._type_byte_size(runtime_type_of(value))

    def _type_byte_size(self, type_name: str):
        """The storage a type occupies, in bytes."""
        from interp.layout import LayoutError, struct_lookup, type_layout
        from interp.units import BUILTIN_UNITS
        try:
            # Asking what a type occupies, not for a C layout, so a
            # width C has no type for still has an answer.
            size, _ = type_layout(type_name, struct_lookup(self.env),
                                  c_compatible=False)
        except LayoutError as e:
            raise coded(2823, TypeError(f"@sizeof: {e}")) from None
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
        if isinstance(expr, (WrapExpr, DropUnitExpr)):
            return self._names_a_binding(expr.expr)
        if isinstance(expr, LimitExpr):
            # A limit is decided by the type it names, so asking about
            # it settles without running anything.
            return True
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
        """Run an arm with what it names bound to the matched value.

        An arm may name the value or, where the value is a tuple, its
        elements.  Either way the names exist only for their arm and
        cannot be assigned to: they name what was matched, and writing
        to one would say nothing about the value that was matched.
        """
        bound: dict[str, Value] = {}
        self._collect_arm_bindings(arm.name, value, bound, arm)
        restore = {name: self._frozen_vars.get(name) for name in bound}
        for name, bound_value in bound.items():
            self.env.define(name, bound_value)
            self._frozen_vars[name] = "match"
        try:
            return self.eval_stmts(arm.body)
        finally:
            for name, old_frozen in restore.items():
                if old_frozen is None:
                    self._frozen_vars.pop(name, None)
                else:
                    self._frozen_vars[name] = old_frozen

    def _collect_arm_bindings(self, names, value, bound: dict, arm):
        """Work out what an arm's pattern binds, taking tuples apart."""
        if not isinstance(names, tuple):
            bound[names] = value
            return
        inner = unwrap_optional(value)
        if not isinstance(inner, TupleValue):
            raise coded(2748, TypeError(
                f"the arm names the elements of a tuple, but the value "
                f"matched is {runtime_type_of(inner)}"))
        if len(inner.elements) != len(names):
            raise coded(2249, TypeError(
                f"the arm names {len(names)} elements, but the value "
                f"matched has {len(inner.elements)}"))
        for name, element in zip(names, inner.elements):
            if name == DISCARD_NAME:
                continue
            self._collect_arm_bindings(name, element, bound, arm)

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
            raise coded(2012, TypeError(
                "catch requires enclosing function to have optional or expected return type"))

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
                raise coded(2250, TypeError(
                    "\N{APL FUNCTIONAL SYMBOL RHO}: dimensions must be non-negative"))

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
                raise coded(2749, TypeError(
                    "\N{APL FUNCTIONAL SYMBOL RHO}: cannot reshape empty array"))
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

    def _eval_map(self, node: MapExpr) -> Value:
        """Evaluate `f ¨ v` -- what f says of each of them.

        Every operator in the language already threads over what it is
        handed, so this is for the functions that do not: an ordinary
        one, a lambda, anything that can be called.  What comes back is
        an array of the answers, one for each, in the order they were
        held.
        """
        func = self.eval_expr(node.func)
        held = unwrap_optional(self.eval_expr(node.container))
        if isinstance(held, RangeValue):
            elements = [mk_int(i) for i in held.to_list()]
        elif isinstance(held, ObjectValue) and isinstance(held.obj, ArrayValue):
            elements = held.obj.values()
        else:
            raise TypeError(
                f"\N{DIAERESIS} asks something of each of an array or a "
                f"range, and this is {self._value_type_name(held)}")
        return ObjectValue(ArrayValue([self._do_call(func, [e])
                                       for e in elements]))

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
            raise coded(2750, TypeError(
                f"fold requires array or range, got {type(cu).__name__}"))

        if node.init is not None:
            acc = self.eval_expr(node.init)
        else:
            if not elements:
                raise coded(2251, TypeError("fold on empty container requires an initial value"))
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
            # An uncommitted literal answers with the type it settles
            # on, which is what the program would write for it.
            return "int" if u.width == UNTYPED else u.width
        if isinstance(u, FloatValue):
            return u.width
        if isinstance(u, StrValue):
            return "str"
        if isinstance(u, CharValue):
            return "char"
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
            # A tuple says what it is the way its type is written, so
            # @typeof answers with something a program could put in a
            # signature rather than with the word "tuple".
            return "(" + ", ".join(
                Evaluator._value_type_name(e) for e in u.elements) + ")"
        if isinstance(u, EnumValue):
            return u.enum_type.name
        if isinstance(u, ObjectValue) and isinstance(u.obj, StructInstance):
            return u.obj.struct_type.name
        if isinstance(u, ObjectValue) and isinstance(u.obj, ArrayValue):
            return Evaluator._array_type_name_of(u.obj)
        if isinstance(u, ObjectValue) and isinstance(u.obj, (HashValue,
                                                             SetValue)):
            return runtime_type_of(u)
        if isinstance(u, RangeValue):
            return "range"
        if isinstance(u, TypeValue):
            return "type"
        return "unknown"

    @staticmethod
    def _array_type_name_of(arr) -> str:
        """The type of an array, written the way a type is written.

        "array" said the same thing about every one of them, which is
        not enough to tell two apart: what an array is is what it holds
        and what shape it holds it in, and both are written down in the
        type a program would give it.
        """
        dims = array_shape(arr)
        leaf = arr.element_type
        parsed = _parse_array_type(leaf) if leaf is not None else None
        while parsed is not None:
            leaf = parsed[0]
            parsed = _parse_array_type(leaf)
        if leaf is None:
            # Nothing was written down, so what it holds is what the
            # first thing in it is.
            probe = arr
            while probe is not None and probe.sizeof:
                first = unwrap_optional(probe.get(0))
                inner = Evaluator._as_array(first)
                if inner is None:
                    leaf = Evaluator._value_type_name(first)
                    break
                probe = inner
        if leaf is None:
            # An empty array that was never told, which is the one case
            # with nothing to report but its shape.
            return "array"
        return _array_type_name(leaf, dims)

    def _eval_lambda_expr(self, node: LambdaExpr):
        """Evaluate a lambda expression: validate captures and build LambdaValue.

        A lambda's parameters and return type are declarations like any
        others, so a type the bootstrap does not provide is refused
        here as it is at a function.
        """
        for param_name, param_type in node.params:
            if param_type is not None:
                check_bootstrap_type(
                    param_type,
                    f"\N{GREEK SMALL LETTER LAMDA}: parameter "
                    f"'{param_name}'")
        if node.ret_type:
            check_bootstrap_type(
                node.ret_type, "\N{GREEK SMALL LETTER LAMDA}: return type")

        refs = _collect_refs(node.body)
        refs -= _parameter_names(node.params)

        lambda_env = Env()
        capture_set = set(node.captures) if node.captures else set()

        if node.captures is not None:
            for name in node.captures:
                try:
                    val = self.env.lookup(name)
                except KeyError:
                    raise coded(2111, TypeError(
                        f"lambda capture '{name}' is not defined"))
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
                raise coded(2252, TypeError(
                    f"lambda references '{name}' but has no capture list"))

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
            display = (_names_display(pname) if isinstance(pname, tuple)
                       else pname)
            if ptype is not None:
                arg = coerce_arg(arg, ptype, "\N{GREEK SMALL LETTER LAMDA}",
                                 display)
            if isinstance(pname, tuple):
                self._bind_parameter_names(
                    pname, arg, call_env, "\N{GREEK SMALL LETTER LAMDA}")
                continue
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
            raise coded(2253, TypeError(
                f"generate: second argument must be a range, "
                f"got {type(range_val).__name__}"))
        elements: list[Value] = []
        for i in range_val.to_list():
            result = self._do_call(func, [mk_int(i)])
            if is_none(result):
                raise coded(2254, TypeError(
                    "generate: function must not return \N{EMPTY SET}"))
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
                raise coded(2824, TypeError(
                    f"struct '{node.name}' has no field '{field_name}'"))
            value = self.eval_expr(field_expr)
            funit = struct_type.field_unit(field_name)
            if funit is not None:
                # a measured field coerces the way a measured binding
                # does: the number to the type, then the unit onto it
                value = coerce_to_type(value, found_type, funit,
                                       self._mk_int)
            else:
                value = coerce_arg(value, found_type, node.name, field_name)
            field_values[field_name] = value
        for fname, ftype in struct_type.fields:
            if fname not in field_values:
                raise coded(2825, TypeError(
                    f"missing field '{fname}' in struct '{node.name}' literal"))
        return ObjectValue(StructInstance(struct_type, field_values))

    # ------------------------------------------------------------------
    # Function calls
    # ------------------------------------------------------------------

    def _module_lookup(self, name: str):
        """A name written unqualified, found the way a module sees it.

        The module in hand first, then the ones it is written inside,
        then the global module.  Nothing found this way can be hidden:
        every candidate is in the current module or one it is written
        inside, and a module hides nothing from what it contains.
        """
        where = self._cur_module
        while True:
            cand = f"{where}.{name}" if where else name
            try:
                return self.env.lookup(cand)
            except KeyError:
                pass
            if not where:
                raise KeyError(f"undefined variable: {name}")
            where = where.rsplit(".", 1)[0] if "." in where else ""

    def _call_func(self, name: str, args):
        """Call a function by name with given arguments.

        Looks up the function in the environment, dispatching to user-defined
        functions (FuncValue) or builtins (BuiltinFunc/BuiltinBoundMethod).
        """
        func = self._module_lookup(name) if MODULES else self.env.lookup(name)
        return self._do_call(func, args)

    def _call_method(self, obj: Value, method_name: str, args):
        """Call a method on an object value.

        For builtin-style methods (like StdModule.sha256(args)) that accept a
        single list of already-evaluated Values, we detect this by checking the
        method signature — if it has exactly one parameter named "args" after
        self, we pass the list as-is.  Otherwise we unpack args for ordinary
        Python methods like ``fs.cwd()``.
        """
        unwrapped = unwrap_optional(obj)
        if method_name == "__call__":
            return self._do_call(unwrapped, args)
        # The hot path first: a struct's method and an array's push,
        # pop and get are most method calls in a large program, and
        # neither needs the ladder below.
        if type(unwrapped) is ObjectValue:
            _o = unwrapped.obj
            if type(_o) is StructInstance:
                method = _o.struct_type.methods.get(method_name)
                if method is not None:
                    if method.params and method.params[0][0] == "self":
                        return self._call_user_func(
                            method, [unwrapped, *args])
                    return self._call_user_func(method, list(args))
            elif type(_o) is ArrayValue and method_name in _ARRAY_METHODS:
                self._check_builtin_args(method_name, args)
                return self._call_array_method(_o, method_name, args)
        if isinstance(unwrapped, StrValue):
            if method_name == "chars":
                if args:
                    raise TypeError("str.chars takes no arguments")
                # The characters a string is made of, as an array, so
                # what iterating hands over one at a time can be held
                # and indexed and handed on.
                return ObjectValue(ArrayValue(
                    [CharValue(ord(c)) for c in unwrapped.value],
                    element_type="char"))
            raise coded(2751, AttributeError(
                f"a string has no method '{method_name}'; it answers "
                f"chars() with what it is made of"))
        if isinstance(unwrapped, SyntaxValue):
            return self._call_syntax_method(unwrapped, method_name, args)
        if isinstance(unwrapped, CharValue):
            if method_name == "str":
                if args:
                    raise TypeError("char.str takes no arguments")
                return mk_str(unwrapped.char)
            if method_name != "ord":
                raise coded(2752, AttributeError(
                    f"a character has no method '{method_name}'; it answers "
                    f"ord() with its number and str() with a string of one"))
            if args:
                raise TypeError("char.ord takes no arguments")
            return mk_int(unwrapped.code, "u32")
        if isinstance(unwrapped, EnumValue) and method_name == "ord":
            # the number an enumerator stands for, in the enum's own
            # underlying type -- which for a @flag enum is the bit set
            if args:
                raise TypeError("ord takes no arguments")
            return mk_int(unwrapped.value,
                          unwrapped.enum_type.underlying_type or "u64")
        if isinstance(unwrapped, IntValue) and method_name == "chr":
            if args:
                raise TypeError("chr takes no arguments")
            return CharValue(
                check_code_point(unwrapped.value, "chr", stop=True))
        if isinstance(unwrapped, Iterator):
            if method_name != "next":
                raise coded(2255, AttributeError(
                    f"an iterator has no method '{method_name}'; it answers "
                    f"only next()"))
            if args:
                raise coded(2256, TypeError("iterator.next takes no arguments"))
            return unwrapped.next()
        # callstack reads evaluator state, which a plain method on the
        # std object has no way to reach.
        if (method_name == "callstack" and isinstance(unwrapped, ObjectValue)
                and unwrapped.obj is std):
            return self._callstack_value(args)
        # The numeric functions of the standard library are @listable,
        # as the operators are: a container argument is taken apart and
        # the question asked of each element.
        if (isinstance(unwrapped, ObjectValue) and unwrapped.obj is std
                and method_name in _LISTABLE_STD_METHODS
                and any(value_rank(a) > 0 for a in args)):
            threaded = self._thread_level(
                f"std.{method_name}",
                [f"argument {i + 1}" for i in range(len(args))],
                list(args),
                [0] * len(args),
                lambda sub: self._call_method(obj, method_name, sub))
            if threaded is not None:
                return threaded
        if (isinstance(unwrapped, ObjectValue)
                and isinstance(unwrapped.obj, ArrayValue)
                and method_name == "str"):
            # Joining is what ⧺ does, and folding it over an array is
            # what does it to all of them, so an array needs no member
            # function saying the same thing a second way.
            fold = "\N{DOUBLE PLUS}\N{APL FUNCTIONAL SYMBOL SLASH BAR}"
            raise coded(2753, AttributeError(
                f"an array does not answer str(); {fold} joins its "
                f"characters into a string, and {fold} (chars, \"\") does "
                f"so where the array may be empty"))
        if isinstance(unwrapped, ObjectValue) \
                and isinstance(unwrapped.obj, (HashValue, SetValue)):
            return self._call_container_method(
                unwrapped.obj, method_name, args)
        if (isinstance(unwrapped, ObjectValue)
                and isinstance(unwrapped.obj, ArrayValue)
                and method_name in _ARRAY_METHODS):
            self._check_builtin_args(method_name, args)
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
                self._check_builtin_args(method_name, args)
                # Detect builtin-style method: takes exactly one "args" list.
                import inspect
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

                # Wrap non-Value results in ObjectValue; a resource
                # inside a present optional is tracked all the same.
                if not isinstance(result, Value):
                    result = ObjectValue(result)
                return self._track_temporary(result)

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
                self._check_builtin_args(func.name, args)
                if func.is_listable:
                    threaded = self._thread_level(
                        func.name,
                        [f"argument {i + 1}" for i in range(len(args))],
                        list(args),
                        [0] * len(args),
                        lambda sub: self._do_call(func, sub))
                    if threaded is not None:
                        return threaded
                return func.func(args)
            if isinstance(func, BuiltinBoundMethod):
                self._check_builtin_args(func.name, args)
                return func(*args)
            raise TypeError(f"cannot call {type(func).__name__}")
        except (_ReturnSentinel, _PropagatedError):
            raise
        except Exception as e:
            if self._catch_depth > 0:
                raise _PropagatedError(e) from e
            raise

    @staticmethod
    def _check_builtin_args(name: str, args):
        """Refuse an argument the interpreter would hold arbitrarily.

        A builtin states no parameter types, so nothing here settles a
        number on one; what reaches it has to be a number some sized
        type could hold.
        """
        from interp.value import check_bootstrap_argument
        for index, arg in enumerate(args):
            check_bootstrap_argument(arg, f"{name}: argument {index + 1}")

    def _call_user_func(self, func: FuncValue, args):
        """Call a user-defined function, its completion recorded."""
        global _fn_calls_done, _fn_last_name
        if not _watchdog_armed and not _fn_stats_on:
            return self._call_user_func_inner(func, args)
        if _fn_stats_on:
            t0 = _time.monotonic()
            try:
                return self._call_user_func_inner(func, args)
            finally:
                dt = _time.monotonic() - t0
                ent = _fn_stats.get(func.name)
                if ent is None:
                    _fn_stats[func.name] = [1, dt]
                else:
                    ent[0] += 1
                    ent[1] += dt
                _fn_calls_done += 1
                _fn_last_name = func.name
        try:
            return self._call_user_func_inner(func, args)
        finally:
            _fn_calls_done += 1
            _fn_last_name = func.name

    def _call_user_func_inner(self, func: FuncValue, args):
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
            raise coded(2257, TypeError(
                f"{func.name} expects {n_regular} arguments, got {len(args)}"))

        if func.is_listable:
            # Threading is decided once the call is known to be one --
            # after too few arguments have had their chance to curry,
            # and before anything is bound, so that each element meets
            # the parameter for itself: its own coercion, its own unit,
            # its own return check.  What the return type states is
            # what one element answers.
            threaded = self._thread_level(
                func.name,
                [f"'{_names_display(name) if isinstance(name, tuple) else name}'"
                 for name, _ in func.params],
                list(args),
                [declared_rank(ptype) for _, ptype in func.params],
                lambda sub: self._call_user_func(func, sub),
                # A signature that states no return type hands nothing
                # back -- which is what → ∅ says, and why writing it
                # draws a warning.  There is nothing to collect either
                # way, so nothing comes back rather than a row of ∅.
                collect=(func.ret_type is not None
                         and func.ret_type != "\N{EMPTY SET}"),
                fallback_type=func.ret_type)
            if threaded is not None:
                return threaded

        # Slicing copies, and the overwhelmingly common call has
        # exactly the parameters it declares and no pack, where the
        # slice would answer the list it was given.  Nothing below
        # writes through it.
        if has_pack:
            regular_args = args[:n_regular]
            pack_args = args[n_regular:]
        else:
            regular_args = args
            pack_args = []

        resolved_params = func.params
        resolved_ret_type = func.ret_type
        resolved_pack_type = func.pack_param[1] if has_pack else None

        # Whether the signature mentions a generic depends on the
        # signature and nothing else, so it is worked out at the first
        # call and read at every one after.  It was being decided again
        # on each of eleven million calls, over a fresh copy of the
        # parameter list, for an answer that is no for almost every
        # function ever written.
        has_generics = func._has_generics
        if has_generics is None:
            all_typed_params = list(func.params)
            if has_pack and func.pack_param[1] is not None:
                all_typed_params.append(func.pack_param)
            has_generics = any(
                pt is not None and is_generic_type(pt)
                for _, pt in all_typed_params
            ) or (func.ret_type is not None
                  and is_generic_type(func.ret_type))
            func._has_generics = has_generics

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
                        raise coded(2258, TypeError(
                            f"{func.name}: generic type {gname} resolved to "
                            f"'{generic_map[gname]}' but argument '{pname}' "
                            f"has type '{concrete}'"))
                else:
                    generic_map[gname] = concrete

            # A generic binds to whatever it was handed, and some of
            # what a program can hold has no type that can be written
            # down -- a file, a directory, an arena.  The binding still
            # holds the generic to one of them across every position,
            # which is what a generic promises; what it cannot do is
            # put the name in place of the generic, since there is no
            # such name to write.  So only a type a program could have
            # written is substituted, and the rest stay generic, which
            # is what a generic parameter accepts anyway.
            written = {g: c for g, c in generic_map.items() if validate_type(c)}
            # A parameter that is nothing but a generic keeps it.
            # Saying T' is saying "whatever this is", so putting
            # the bound type in its place would have the argument
            # measured against a type nobody wrote -- and refused for
            # carrying a unit, or for being a file, or for being any of
            # the things whose type cannot be written down.  A type
            # built *around* a generic, T'[], does state something of
            # its own, so it is filled in and the shape is checked.
            resolved_params = [
                (n, t if t is not None and _is_bare_generic(t)
                    else (_substitute_generics(t, written) if t else t))
                for n, t in func.params
            ]
            if func.ret_type is not None \
                    and not _is_bare_generic(func.ret_type):
                # A return type that is nothing but a generic says the
                # function hands back what it was given, so it is left
                # alone for the same reason the parameter is.
                resolved_ret_type = _substitute_generics(func.ret_type, written)
            if resolved_pack_type is not None:
                resolved_pack_type = _substitute_generics(resolved_pack_type, written)

        call_env = func.env.copy_for_call()
        # By value means a copy.  The copy is elided wherever it cannot
        # be noticed -- see the by-value branch below, which is the
        # common case -- but here it can: a &mut of the same thing in
        # the same call would otherwise let the callee watch its own
        # by-value argument change under it.  Nearly every call answers
        # this in one comparison, because nearly every call lends
        # nothing.
        _lent_mutably = [
            id(unwrap_optional(a.get()).obj)
            for (pn, _pt), a in zip(resolved_params, regular_args)
            if pn in func.param_muts and isinstance(a, RefValue)
            and isinstance(unwrap_optional(a.get()), ObjectValue)
        ]
        for (param_name, param_type), arg_value in zip(resolved_params, regular_args):
            if isinstance(param_name, tuple):
                # The parameter names the elements of a tuple rather
                # than the tuple, so the argument is taken apart into
                # the call's own environment.
                if param_type is not None:
                    arg_value = coerce_arg(arg_value, param_type, func.name,
                                           _names_display(param_name))
                self._bind_parameter_names(param_name, arg_value, call_env,
                                           func.name)
                continue
            self._check_resizable_argument(func, param_name, param_type,
                                           arg_value)
            is_ref_param = param_name in func.param_refs
            if is_ref_param:
                if not isinstance(arg_value, RefValue):
                    raise coded(2259, TypeError(
                        f"{func.name}: parameter '{param_name}' is by-reference, "
                        f"caller must pass &{param_name}"))
                # Lent rather than given, so nothing is coerced -- what
                # the callee writes goes into the caller's own array.
                # That is the reason to measure it here: the type has
                # to be the caller's already.
                if param_type is not None:
                    lent = unwrap_optional(arg_value.get())
                    if isinstance(lent, ObjectValue) \
                            and isinstance(lent.obj, ArrayValue):
                        try:
                            coerce_arg(lent, param_type, func.name, param_name)
                        except (TypeError, OverflowError) as e:
                            raise coded(2754, TypeError(strip_position_prefix(str(e)))) from None
                call_env.define(param_name, arg_value)
                continue
            if isinstance(arg_value, RefValue):
                raise coded(2260, TypeError(
                    f"{func.name}: parameter '{param_name}' is by-value, "
                    f"caller must not pass a reference"))
            if param_name in func.param_muts:
                arg_value = deep_copy_value(arg_value)
                # The copy takes the parameter's shape: a dynamically-
                # sized parameter yields a dynamic array whatever it was
                # given, as `let d : mut i32[] = f` does.
                if param_type is not None and isinstance(arg_value, ObjectValue) \
                        and isinstance(arg_value.obj, ArrayValue):
                    declared = _parse_array_type(param_type)
                    if declared is not None:
                        arg_value.obj.fixed_size = declared[1][0]
            elif isinstance(arg_value, ObjectValue) \
                    and id(arg_value.obj) in _lent_mutably:
                # …unless this very call lends the same thing mutably,
                # in which case the copy is the whole difference
                # between what the callee was handed and what it would
                # see.
                arg_value = deep_copy_value(arg_value)
            elif isinstance(arg_value, ObjectValue) \
                    and isinstance(arg_value.obj, ArrayValue):
                # A by-value parameter that cannot be written through
                # may alias the caller's array -- every write path is
                # refused -- so the element-by-element copy bought
                # nothing but the time it took, which for the compiler
                # compiling itself was the input's length at every
                # call.  Only a shape change still copies.
                if param_type is not None:
                    declared = _parse_array_type(param_type)
                    if declared is not None \
                            and arg_value.obj.fixed_size != declared[1][0]:
                        arg_value = deep_copy_value(arg_value)
                        arg_value.obj.fixed_size = declared[1][0]
            param_unit = None
            if param_name in func.param_units:
                from interp.units import eval_unit_formula
                param_unit = eval_unit_formula(func.param_units[param_name])
                if isinstance(arg_value, IntValue) \
                        and not is_unwidthed(arg_value.width):
                    raise coded(2323, TypeError(
                        f"{func.name}: parameter '{param_name}' requires unit "
                        f"{param_unit.display_name}, got typed integer "
                        f"{arg_value.width} without unit"))
                # An array is measured by its elements, so the unit
                # reaches them rather than the argument as a whole.
                arg_value = apply_unit(arg_value, param_unit, self._mk_int)
            if param_type is not None:
                if param_unit is not None:
                    arg_value = coerce_arg(arg_value, param_type, func.name,
                                           param_name, unit=param_unit)
                else:
                    arg_value = coerce_arg(arg_value, param_type,
                                           func.name, param_name)
            if param_type is None or _is_bare_generic(param_type):
                # A generic settles nothing either -- it takes the value
                # as it is -- so what arrives still has to be a number
                # some sized type could hold.
                check_bootstrap_argument(
                    arg_value, f"{func.name}: parameter '{param_name}'")
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
        old_frozen = self._frozen_vars
        old_generic_map = self._generic_map
        old_comptime_vars = self._comptime_vars
        old_module = self._cur_module
        # The callee's frame starts fresh: a name the caller's loop or
        # borrow froze is not the callee's name, however it is spelled.
        self._frozen_vars = {}
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
        # The parameters' names, likewise settled once: the scope that
        # is ending does not own them, and which they are cannot change
        # between calls.
        borrowed = func._param_names
        if borrowed is None:
            names = {name for name, _ in func.params}
            if has_pack:
                names.add(func.pack_param[0])
            borrowed = frozenset(names)
            func._param_names = borrowed
        try:
            self.env = call_env
            self._current_ret_type = resolved_ret_type
            self._pure_func_name = None if func.is_impure else func.name
            self._cur_module = func.module
            self._generic_map = generic_map
            # A copy, because a foreach inside the body adds its own
            # names to this and takes them out again; copying a
            # frozenset is a great deal cheaper than walking the
            # parameters to build one.
            self._comptime_vars = set(borrowed)
            self._check_conditions(func, func.preconditions)
            result = self.eval_stmts(func.body)
            result = self._check_return_type(
                result, resolved_ret_type, func.name, func.ret_unit)
            returned = self._wrap_optional_return(result, resolved_ret_type)
            self._check_conditions(func, func.postconditions, returned)
            return returned
        except _ReturnSentinel as e:
            checked = self._check_return_type(
                e.value, resolved_ret_type, func.name, func.ret_unit)
            returned = self._wrap_optional_return(checked, resolved_ret_type)
            self._check_conditions(func, func.postconditions, returned)
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
            self._cur_module = old_module

    def _track_temporary(self, value):
        """Note a freshly produced resource so an unkept one can be released.

        A resource that is never assigned to anything has no binding to
        own it and no scope to end, so without this it would survive
        until the program exits.  `std.fs.cwd().open_file(name)` is the
        motivating case: the directory exists only to reach the file.
        """
        held = value.value if isinstance(value, SomeValue) else value
        if self._temporaries is not None and isinstance(held, ObjectValue):
            if callable(getattr(held.obj, "destroy", None)):
                if self._temporaries is _NO_TEMPS:
                    self._temporaries = []
                self._temporaries.append(held.obj)
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
                if isinstance(bound, SomeValue):
                    bound = bound.value
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

    def _end_scope(self, call_env, returned, borrowed: frozenset):
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
            borrowed: names of bindings this scope does not own,
                which the function it belongs to settled once.
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
            # a resource may sit inside a present optional, as an
            # open_file answer bound whole does
            if isinstance(value, SomeValue):
                value = value.value
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
        carried = self._carried_unit(inner)
        if carried is not None and carried is not _EMPTY_MEASURE \
                and not carried.same_dimension(want):
            raise TypeError(
                f"{func_name}: return type is {ret_type} "
                f"\N{CURRENCY SIGN}{want.display_name}, but the body evaluates to "
                f"{carried.display_name}")
        # An array is measured by its elements, so the unit reaches
        # them rather than the value as a whole.
        settled = apply_unit(inner, want, self._mk_int)
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
        if _is_bare_generic(check):
            # The type says the function hands back what it was given,
            # so what came back is what was promised, unit and all.
            return result
        inner = result
        rewrap = None
        if isinstance(inner, SomeValue):
            inner, rewrap = inner.value, SomeValue
        elif isinstance(inner, ExpectedValue):
            if inner.is_ok():
                inner, rewrap = inner.ok_value, ExpectedValue.ok
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
        # A return type states what leaves the function, so an array
        # meeting one that names no array is refused as it would be at
        # a binding or a parameter.
        mismatch = array_type_mismatch(inner, check)
        if mismatch is not None:
            raise coded(2755, TypeError(f"{func_name}: {mismatch}"))
        if _parse_array_type(check) is not None:
            # And what the array holds is measured too, as it is at a
            # parameter: a return type naming an array of numbers is
            # not answered by an array of something else.
            try:
                settled = coerce_to_type(inner, check)
            except (TypeError, OverflowError) as e:
                raise coded(2756, TypeError(
                    f"{func_name}: return type is {ret_type}, but "
                    f"{strip_position_prefix(str(e))}")) from None
            return rewrap(settled) if rewrap is not None else settled
        if check in _TYPE_BITS or check == "int":
            if isinstance(inner, FloatValue):
                raise coded(2261, TypeError(
                    f"{func_name}: return type is {ret_type} "
                    f"but body evaluates to "
                    f"{self._value_type_name(inner)}"))
            if isinstance(inner, (StrValue, BoolValue)):
                raise coded(2262, TypeError(
                    f"{func_name}: return type is {ret_type} "
                    f"but body evaluates to {self._value_type_name(inner)}"))
            if isinstance(inner, IntValue):
                return coerce_to_type(inner, check) if opt_err is None else result
        elif check in FLOAT_TYPES:
            if isinstance(inner, IntValue):
                raise coded(2263, TypeError(
                    f"{func_name}: return type is {ret_type} "
                    f"but body evaluates to "
                    f"{self._value_type_name(inner)}"))
            if isinstance(inner, (StrValue, BoolValue)):
                raise TypeError(
                    f"{func_name}: return type is {ret_type} "
                    f"but body evaluates to {self._value_type_name(inner)}")
            if isinstance(inner, FloatValue):
                # The signature decides the width, as it does for an
                # integer: a value leaving through it is of the type it
                # names, and one the type cannot hold is refused here
                # rather than travelling as an infinity.
                try:
                    return (coerce_to_type(inner, check) if opt_err is None
                            else result)
                except OverflowError as e:
                    raise TypeError(f"{func_name}: {e}") from None
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


class _LoopSignal(BaseException):
    """Leaving a loop, or going round it again.

    Carries the label the statement named, or None for the loop it
    sits directly inside.  A loop catches the signals that are its own
    and lets the rest travel outward, which is how a label reaches a
    loop that is not the innermost.
    """

    __slots__ = ("label",)

    def __init__(self, label=None):
        super().__init__(label)
        self.label = label


class _BreakSignal(_LoopSignal):
    """`break`."""


class _ContinueSignal(_LoopSignal):
    """`continue`."""


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


# Expression dispatch: one dict probe instead of a ladder walk.
_EXPR_DISPATCH = {
    IntLit: Evaluator._ee_IntLit,
    FloatLit: Evaluator._ee_FloatLit,
    CharLit: Evaluator._ee_CharLit,
    StrLit: Evaluator._ee_StrLit,
    BoolLit: Evaluator._ee_BoolLit,
    NoneLit: Evaluator._ee_NoneLit,
    VarRef: Evaluator._ee_VarRef,
    BinOp: Evaluator._ee_BinOp,
    UnaryOp: Evaluator._ee_UnaryOp,
    OptSome: Evaluator._ee_OptSome,
    StructLit: Evaluator._ee_StructLit,
    FuncCall: Evaluator._ee_FuncCall,
    MethodCall: Evaluator._ee_MethodCall,
    GetAttr: Evaluator._ee_GetAttr,
    ArrayLit: Evaluator._ee_ArrayLit,
    RangeExpr: Evaluator._ee_RangeExpr,
    IfExpr: Evaluator._ee_IfExpr,
    DropUnitExpr: Evaluator._ee_DropUnitExpr,
    RefExpr: Evaluator._ee_RefExpr,
    StaticAssert: Evaluator._ee_StaticAssert,
    StaticAssertEq: Evaluator._ee_StaticAssertEq,
    UnitExpr: Evaluator._ee_UnitExpr,
    ExpErr: Evaluator._ee_ExpErr,
    TryUnwrap: Evaluator._ee_TryUnwrap,
    HashLit: Evaluator._ee_HashLit,
    SetLit: Evaluator._ee_SetLit,
    EmptyCollectionLit: Evaluator._ee_EmptyCollectionLit,
    MultiSlice: Evaluator._ee_MultiSlice,
    EnumerateExpr: Evaluator._ee_EnumerateExpr,
    TypeOfExpr: Evaluator._ee_TypeOfExpr,
    LimitExpr: Evaluator._ee_LimitExpr,
    Quote: Evaluator._ee_Quote,
    Reflect: Evaluator._ee_Reflect,
    Splice: Evaluator._ee_Splice,
    SizeOfExpr: Evaluator._ee_SizeOfExpr,
    ResultOfExpr: Evaluator._ee_ResultOfExpr,
    UnitOfExpr: Evaluator._ee_UnitOfExpr,
    UnitRefExpr: Evaluator._ee_UnitRefExpr,
    LambdaExpr: Evaluator._ee_LambdaExpr,
    TupleLit: Evaluator._ee_TupleLit,
    OperatorRef: Evaluator._ee_OperatorRef,
    FoldExpr: Evaluator._ee_FoldExpr,
    MapExpr: Evaluator._ee_MapExpr,
    ReshapeExpr: Evaluator._ee_ReshapeExpr,
}


# Statement dispatch, the same one-probe shape as expressions.
_STMT_DISPATCH = {
    ExpectStmt: Evaluator._es_ExpectStmt,
    VarDef: Evaluator._es_VarDef,
    DestructureDef: Evaluator._es_DestructureDef,
    SumTypeDef: Evaluator._es_SumTypeDef,
    TypeDef: Evaluator._es_TypeDef,
    ExprStmt: Evaluator._es_ExprStmt,
    IfStmt: Evaluator._es_IfStmt,
    WhileStmt: Evaluator._es_WhileStmt,
    ForEachStmt: Evaluator._es_ForEachStmt,
    MatchStmt: Evaluator._es_MatchStmt,
    CatchStmt: Evaluator._es_CatchStmt,
    ReturnStmt: Evaluator._es_ReturnStmt,
}
