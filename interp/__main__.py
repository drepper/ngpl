"""Entry point for the NGPL prototype interpreter."""

import argparse
import re
import signal
import sys
import os
from collections import defaultdict

from interp.lexer import tokenize, process_indentation
from interp.parser import Parser
from interp.macros import (collect as macro_collect,
                           expand_definitions as macro_expand, MacroError,
                           COMPTIME as MACRO_COMPTIME,
                           FUNCTIONS as MACRO_SEEN_FUNCTIONS)
from interp.env import Env, Decl
from interp.ast import (
    FuncDef as ASTFuncDef, EnumDef as ASTEnumDef, UnitDef as ASTUnitDef,
    VarDef as ASTVarDef, TypeDef as ASTTypeDef,
    DestructureDef as ASTDestructureDef,
    StructDef as ASTStructDef, ImplBlock as ASTImplBlock,
)
import interp.ast as _ast
from interp.value import (
    check_bootstrap_binding, check_binding_settles, check_int,
    FuncValue, BuiltinFunc, ObjectValue, IntValue, StrValue, BoolValue, ArrayValue,
    HashValue, SetValue,
    NoneValue, SomeValue, ExpectedValue, EnumType, EnumValue, StructType,
    coerce_to_type, apply_unit, validate_param_type, validate_type, none, FAST_TYPES,
    register_type_alias, register_sum_type, register_enum_type,
    sum_type_alternatives, register_user_type, DISCARD_NAME, is_type_name,
    register_struct_type,
    UnitValue,
    _split_optional_type, _TYPE_BITS, FLOAT_TYPES, resolve_type_alias,
    check_bootstrap_type,
    _parse_array_type, format_shape, is_generic_type, declared_rank,
    a_sum_holds_both,
)
from interp.eval import Evaluator, unwrap_optional, _ARRAY_MUTATORS

# Methods that only look at their object, whatever its type turns out
# to be.  Every other method may reach a &mut self and change it.
_KNOWN_READONLY_METHODS = frozenset({
    "get", "iterate", "next", "str", "ord", "chr", "chars", "shape",
})
from interp.layout import LayoutError, struct_layout, struct_lookup
from interp.errors import (format_diagnostic, extract_position,
                           strip_position_prefix, format_backtrace,
                           diagnostic_level, set_warnings_are_errors,
                           warnings_are_errors, set_contract_semantic,
                           set_source, CONTRACT_SEMANTICS,
                           ProgramExit, ProgramAbort)


def _make_std_errors() -> EnumType:
    """Create the std.errors enum with error codes grouped by category."""
    members = {
        # Runtime errors (100-199)
        "division_by_zero": 100,
        "shift_out_of_range": 106,
        "index_out_of_range": 101,
        "stack_overflow": 102,
        "null_dereference": 103,
        "integer_overflow": 104,
        "assertion_failed": 105,
        # Compile-time errors (200-299)
        "type_mismatch": 200,
        "unknown_type": 201,
        "syntax_error": 202,
        "undefined_variable": 203,
        "arity_mismatch": 204,
        # Library/runtime function errors (300-399)
        "file_not_found": 300,
        "permission_denied": 301,
        "io_error": 302,
        "allocation_failed": 303,
        "invalid_argument": 304,
    }
    return EnumType("errors", "u16", members, is_flag=False)


def setup_std_env(env: Env, program: str = "", program_args: list[str] | None = None):
    """Register the std module and assertion builtins in the given environment.

    The program name and its arguments are handed to std.args so that the
    interpreted program can read its own command line.
    """
    from interp.std import std, make_file_type_enum
    std.errors = _make_std_errors()
    std.filetype = make_file_type_enum()
    std.args.set_command_line(program, program_args or [])
    env.define("std", ObjectValue(std))
    env.define("assert", BuiltinFunc("assert", -1, _builtin_assert))
    env.define("assert_eq", BuiltinFunc("assert_eq", 2, _builtin_assert_eq))
    env.define("generate", BuiltinFunc("generate", 2, None))


def _builtin_assert(args):
    """assert(condition) or assert(condition, message)."""
    if len(args) < 1:
        raise TypeError("assert requires at least 1 argument")
    cond = unwrap_optional(args[0])
    if isinstance(cond, BoolValue):
        if not cond.value:
            msg = ""
            if len(args) > 1:
                msg = str(unwrap_optional(args[1]).to_python())
            raise AssertionError(f"assertion failed: {msg}" if msg else "assertion failed")
    elif isinstance(cond, IntValue):
        if cond.value == 0:
            raise AssertionError("assertion failed: value is zero")
    else:
        raise TypeError(f"assert condition must be bool or int, got {type(cond).__name__}")
    return none()


def _format_value(v) -> str:
    """Format a value for assertion error messages."""
    if isinstance(v, IntValue):
        if v.value.bit_length() > 32 or v.value < 0:
            return format(v.value, "x")
        return str(v.value)
    if isinstance(v, ObjectValue) and isinstance(v.obj, ArrayValue):
        arr = v.obj
        elems = ", ".join(_format_value(arr.get(i)) for i in range(arr.sizeof))
        return f"[{elems}]"
    return v.display()


def _values_equal(a, b) -> bool:
    """Deep equality check for assertion comparisons."""
    a, b = unwrap_optional(a), unwrap_optional(b)
    if isinstance(a, IntValue) and isinstance(b, IntValue):
        return a.value == b.value
    if (isinstance(a, ObjectValue) and isinstance(a.obj, ArrayValue)
            and isinstance(b, ObjectValue) and isinstance(b.obj, ArrayValue)):
        aa, ba = a.obj, b.obj
        return (aa.sizeof == ba.sizeof
                and all(_values_equal(aa.get(i), ba.get(i)) for i in range(aa.sizeof)))
    if (isinstance(a, ObjectValue) and isinstance(a.obj, SetValue)
            and isinstance(b, ObjectValue) and isinstance(b.obj, SetValue)):
        # Order is not part of it, as it is not for = between two.
        return (a.obj.sizeof == b.obj.sizeof
                and all(b.obj.has(v) for v in a.obj.values()))
    if (isinstance(a, ObjectValue) and isinstance(a.obj, HashValue)
            and isinstance(b, ObjectValue) and isinstance(b.obj, HashValue)):
        return (a.obj.sizeof == b.obj.sizeof
                and all(b.obj.has(k) and _values_equal(b.obj.get(k), v)
                        for k, v in a.obj.pairs()))
    try:
        return a.to_python() == b.to_python()
    except Exception:
        return False


def _builtin_assert_eq(args):
    """assert_eq(expected, actual) -- fail if values differ."""
    if len(args) != 2:
        raise TypeError("assert_eq requires exactly 2 arguments")
    a0, a1 = args[0], args[1]
    Evaluator._reject_mixed_optional(a0, a1, "assert_eq")
    # Compared by shape first, so ∃(∅) and ∅ are not reported as equal.
    if isinstance(a0, (SomeValue, NoneValue)):
        a0_present = isinstance(a0, SomeValue)
        a1_present = isinstance(a1, SomeValue)
        if a0_present != a1_present:
            raise AssertionError(
                f"assert_eq failed:\n  expected: {a0.display()}\n"
                f"  actual:   {a1.display()}")
        if not a0_present:
            return none()
        return _builtin_assert_eq([a0.value, a1.value])
    if isinstance(a0, ExpectedValue) and isinstance(a1, ExpectedValue):
        if a0.is_ok() and a1.is_ok():
            return _builtin_assert_eq([a0.ok_value, a1.ok_value])
        if a0.is_err() and a1.is_err():
            return _builtin_assert_eq([a0.err_value, a1.err_value])
        raise AssertionError(
            f"assert_eq failed:\n  expected: {a0.display()}\n  actual:   {a1.display()}")
    expected = unwrap_optional(a0)
    actual = unwrap_optional(a1)
    if isinstance(expected, EnumValue) and isinstance(actual, EnumValue):
        if expected.enum_type is not actual.enum_type or expected.value != actual.value:
            raise AssertionError(
                f"assert_eq failed:\n  expected: {expected.display()}\n  actual:   {actual.display()}")
    elif isinstance(expected, EnumValue) and isinstance(actual, IntValue):
        if expected.value != actual.value:
            raise AssertionError(
                f"assert_eq failed:\n  expected: {expected.display()}\n  actual:   {_format_value(actual)}")
    elif isinstance(expected, IntValue) and isinstance(actual, EnumValue):
        if expected.value != actual.value:
            raise AssertionError(
                f"assert_eq failed:\n  expected: {_format_value(expected)}\n  actual:   {actual.display()}")
    elif isinstance(expected, IntValue) and isinstance(actual, IntValue):
        if expected.value != actual.value:
            raise AssertionError(
                f"assert_eq failed:\n  expected: {_format_value(expected)}\n  actual:   {_format_value(actual)}")
    elif (isinstance(expected, ObjectValue) and isinstance(expected.obj, ArrayValue)
          and isinstance(actual, ObjectValue) and isinstance(actual.obj, ArrayValue)):
        ea, aa = expected.obj, actual.obj
        if ea.sizeof != aa.sizeof or any(
                not _values_equal(ea.get(i), aa.get(i)) for i in range(ea.sizeof)):
            raise AssertionError(
                f"assert_eq failed:\n  expected: {_format_value(expected)}\n  actual:   {_format_value(actual)}")
    elif (isinstance(expected, ObjectValue)
          and isinstance(expected.obj, (HashValue, SetValue))) \
            or (isinstance(actual, ObjectValue)
                and isinstance(actual.obj, (HashValue, SetValue))):
        if not _values_equal(expected, actual):
            raise AssertionError(
                f"assert_eq failed:\n  expected: {_format_value(expected)}\n  actual:   {_format_value(actual)}")
    elif expected.to_python() != actual.to_python():
        raise AssertionError(
            f"assert_eq failed:\n  expected: {_format_value(expected)}\n  actual:   {_format_value(actual)}")
    return none()


if sys.stderr.isatty():
    _GREEN = "\033[32m"
    _RED = "\033[31m"
    _BOLD = "\033[1m"
    _RESET = "\033[0m"
else:
    _GREEN = _RED = _BOLD = _RESET = ""


def _run_test(test_fv: FuncValue, env: Env, source: str = "",
              source_path: str = "") -> tuple[bool, str]:
    """Run a single test function, return (passed, report).

    A failing test reports where it failed, with the offending line and
    a caret, and the call chain when the failure is deeper than the test
    body.  A bare message leaves the reader to find the line themselves,
    which for an assertion buried in a helper can mean reading the whole
    file.
    """
    evaluator = Evaluator(env)
    try:
        evaluator._call_user_func(test_fv, [])
        return True, ""
    except Exception as e:
        return False, _test_failure_report(e, evaluator, source, source_path)


def _test_failure_report(exc: BaseException, evaluator: Evaluator,
                         source: str, source_path: str) -> str:
    """Format a test failure the way other diagnostics are formatted."""
    message = strip_position_prefix(
        str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc))
    # "assert_eq failed: ..." already says what happened; prefixing it
    # with "assertion failed" would say it twice.
    if isinstance(exc, AssertionError) and not message.lower().startswith("assert"):
        message = f"assertion failed: {message}"

    position = extract_position(exc) or evaluator._last_pos
    if position is None or not source:
        return message

    line, col, end_col = position
    report = format_diagnostic(source, source_path, line, col, message,
                               end_col=end_col, level="error")
    trace = format_backtrace(exc, source_path)
    if trace is not None:
        report += "\n" + trace
    return report


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the interpreter."""
    parser = argparse.ArgumentParser(
        # The name the interpreter is invoked as, which is what a usage
        # line is for; NGPL is the language it runs.
        prog="ngpli",
        description="Prototype interpreter for the NGPL programming language.",
    )
    parser.add_argument("sources", nargs="*", metavar="SOURCE",
                        help="source files to interpret, read as if they were "
                             "one file concatenated in the order given; "
                             "without any the interpreter starts a REPL.  "
                             "Name them together -- an option written between "
                             "two of them is not understood")
    parser.add_argument("--repl", action="store_true",
                        help="enter the REPL after loading the source instead "
                             "of running the startup function")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--test", action="store_true",
                       help="run all tests and exit without executing the startup function")
    group.add_argument("--skip-tests", action="store_true",
                       help="skip all tests during normal execution")
    parser.add_argument("--start", metavar="NAME",
                       help="use the named function as the startup function, "
                            "ignoring any @start annotations")
    parser.add_argument("-Werror", dest="werror", action="store_true",
                       help="treat every warning as an error, and read an "
                            "@expect warning as @expect error")
    parser.add_argument("--contracts", metavar="SEMANTIC",
                       choices=CONTRACT_SEMANTICS, default="enforce",
                       help="what a @pre or @post that does not hold does: "
                            "ignore (the condition is not read at all), "
                            "observe (report it and carry on), enforce "
                            "(report it and stop, the default), or "
                            "quick-enforce (stop at once, reporting "
                            "nothing).  The four are C++26's evaluation "
                            "semantics")
    parser.add_argument("--interpreter-backtrace", action="store_true",
                       help="show the Python interpreter backtrace on errors")
    parser.add_argument("--timeout", metavar="SECONDS", type=float,
                       default=None,
                       help="stop the program with a backtrace when it has "
                            "not finished after this many seconds; the "
                            "NGPLI_TIMEOUT environment variable sets the "
                            "same limit for every run")
    parser.add_argument("--heartbeat", metavar="SECONDS", type=float,
                       nargs="?", const=10.0, default=None,
                       help="report progress on stderr (elapsed time, "
                            "statements run, where the program is) every "
                            "SECONDS seconds, 10 without a value; the "
                            "NGPLI_HEARTBEAT environment variable does "
                            "the same")
    parser.add_argument("--fn-stats", action="store_true",
                       help="record every user function's calls and "
                            "cumulative time, and print the record when "
                            "the process ends (or the time limit stops "
                            "it); NGPLI_FN_STATS=1 does the same")
    # Everything after a bare `--` belongs to the interpreted program and
    # is split off before argparse sees it, so it is not an argument here.
    ours, theirs = _split_at_separator(sys.argv[1:])
    args = parser.parse_args(ours)
    args.program_args = theirs
    return args


def _split_at_separator(argv: list[str]) -> tuple[list[str], list[str]]:
    """Divide a command line at the first bare `--`.

    The interpreter's own options come first and the interpreted
    program's arguments follow.  argparse.REMAINDER used to draw this
    line, but it cannot: a REMAINDER beside a positional that takes
    several file names swallows the separator along with the files.
    """
    if "--" in argv:
        at = argv.index("--")
        return argv[:at], argv[at + 1:]
    return argv, []


def _show_error(exc: BaseException, source: str, source_path: str,
                evaluator: Evaluator | None = None, *,
                show_backtrace: bool = False) -> None:
    """Display a formatted error diagnostic for a NGPL exception."""
    if show_backtrace:
        import traceback
        traceback.print_exc()
        return

    pos = extract_position(exc)
    if pos is None and evaluator is not None:
        pos = evaluator._last_pos

    msg = strip_position_prefix(str(exc))
    level = "error"
    if isinstance(exc, AssertionError):
        level = "error"
        msg = f"assertion failed: {msg}" if "assertion" not in msg.lower() else msg

    if pos is not None:
        line, col, end_col = pos
        diag = format_diagnostic(source, source_path, line, col, msg,
                                 end_col=end_col, level=level)
        print(diag, file=sys.stderr)
    else:
        if sys.stderr.isatty():
            print(f"\033[31m\033[1merror\033[0m\033[1m: {msg}\033[0m",
                  file=sys.stderr)
        else:
            print(f"error: {msg}", file=sys.stderr)

    trace = format_backtrace(exc, source_path)
    if trace is not None:
        print(trace, file=sys.stderr)


def _report_abort(exc: ProgramAbort, source_path: str,
                  show_backtrace: bool) -> None:
    """Announce an abort, show where it came from, then deliver the signal.

    The backtrace is printed before the signal is raised, because once
    the signal is delivered the process is gone and nothing else runs.
    """
    from interp.std import deliver_abort

    if show_backtrace:
        import traceback
        traceback.print_exc()

    name = signal.Signals(exc.signal_number).name
    if sys.stderr.isatty():
        print(f"{_RED}{_BOLD}aborted{_RESET}{_BOLD}: {name}{_RESET}",
              file=sys.stderr)
    else:
        print(f"aborted: {name}", file=sys.stderr)

    # An abort prints no caret diagnostic, so even a one-frame stack is
    # the only thing telling the user where it came from.
    trace = format_backtrace(exc, source_path, min_frames=1)
    if trace is not None:
        print(trace, file=sys.stderr)

    deliver_abort(exc.signal_number)


def _var_ref_node(expr, name: str):
    """The node in an expression that reads `name`, when one is found.

    A diagnostic about a name reads better pointing at the name than at
    the expression holding it, and the node is where the position is.
    """
    for node in _iter_ast(expr):
        if isinstance(node, _ast.VarRef) and node.name == name:
            return node
    return expr


def _expr_var_refs(expr) -> set[str]:
    """Collect VarRef names referenced in an expression tree."""
    if expr is None:
        return set()
    refs: set[str] = set()
    if isinstance(expr, _ast.VarRef):
        refs.add(expr.name)
    elif isinstance(expr, _ast.BinOp):
        refs |= _expr_var_refs(expr.left)
        refs |= _expr_var_refs(expr.right)
    elif isinstance(expr, _ast.UnaryOp):
        refs |= _expr_var_refs(expr.operand)
    elif isinstance(expr, _ast.FuncCall):
        for a in expr.args:
            refs |= _expr_var_refs(a)
    elif isinstance(expr, _ast.MethodCall):
        refs |= _expr_var_refs(expr.obj)
        for a in expr.args:
            refs |= _expr_var_refs(a)
    elif isinstance(expr, _ast.GetAttr):
        refs |= _expr_var_refs(expr.obj)
    elif isinstance(expr, _ast.StructLit):
        for _, val in expr.field_inits:
            refs |= _expr_var_refs(val)
    elif isinstance(expr, _ast.Subscript):
        refs |= _expr_var_refs(expr.obj)
        for idx in expr.indices:
            refs |= _expr_var_refs(idx)
    elif isinstance(expr, _ast.OptSome):
        refs |= _expr_var_refs(expr.value)
    elif isinstance(expr, _ast.TryUnwrap):
        refs |= _expr_var_refs(expr.expr)
    elif isinstance(expr, _ast.LambdaExpr):
        pass
    return refs


def _find_consuming_calls(expr, struct_vars: dict[str, StructType]) -> set[str]:
    """Find variables consumed by method calls in an expression tree."""
    consumed: set[str] = set()
    if isinstance(expr, _ast.MethodCall):
        if isinstance(expr.obj, _ast.VarRef):
            var_name = expr.obj.name
            if var_name in struct_vars:
                st = struct_vars[var_name]
                method = st.methods.get(expr.method)
                if (method is not None
                        and method.params
                        and method.params[0][0] == "self"
                        and expr.method not in st._ref_self_methods):
                    consumed.add(var_name)
        consumed |= _find_consuming_calls(expr.obj, struct_vars)
        for a in expr.args:
            consumed |= _find_consuming_calls(a, struct_vars)
    elif isinstance(expr, _ast.BinOp):
        consumed |= _find_consuming_calls(expr.left, struct_vars)
        consumed |= _find_consuming_calls(expr.right, struct_vars)
    elif isinstance(expr, _ast.UnaryOp):
        consumed |= _find_consuming_calls(expr.operand, struct_vars)
    elif isinstance(expr, _ast.FuncCall):
        for a in expr.args:
            consumed |= _find_consuming_calls(a, struct_vars)
    elif isinstance(expr, _ast.GetAttr):
        consumed |= _find_consuming_calls(expr.obj, struct_vars)
    return consumed


def _infer_struct_type(expr, env, struct_vars: dict[str, StructType]) -> StructType | None:
    """Infer whether an expression produces a struct instance."""
    if isinstance(expr, _ast.StructLit):
        try:
            st = env.lookup(expr.name)
            if isinstance(st, StructType):
                return st
        except KeyError:
            pass
    elif isinstance(expr, _ast.MethodCall):
        if isinstance(expr.obj, _ast.VarRef):
            try:
                val = env.lookup(expr.obj.name)
                if isinstance(val, StructType):
                    method = val.methods.get(expr.method)
                    if method is not None and method.ret_type == val.name:
                        return val
            except KeyError:
                pass
            if expr.obj.name in struct_vars:
                st = struct_vars[expr.obj.name]
                method = st.methods.get(expr.method)
                if method is not None and method.ret_type == st.name:
                    return st
    elif isinstance(expr, _ast.FuncCall):
        try:
            fv = env.lookup(expr.name)
            if isinstance(fv, FuncValue) and fv.ret_type:
                try:
                    st = env.lookup(fv.ret_type)
                    if isinstance(st, StructType):
                        return st
                except KeyError:
                    pass
        except KeyError:
            pass
    return None


def _stmt_top_exprs(stmt) -> list:
    """Return expressions that should be checked for moved-variable reads."""
    if isinstance(stmt, _ast.ExprStmt):
        return [stmt.expr]
    if isinstance(stmt, ASTVarDef):
        return [stmt.init_expr] if stmt.init_expr else []
    if isinstance(stmt, tuple) and len(stmt) == 3 and stmt[0] == "assign_stmt":
        target = stmt[1]
        result = [stmt[2]]
        if isinstance(target, _ast.GetAttr):
            result.append(target.obj)
        elif isinstance(target, _ast.Subscript):
            result.append(target.obj)
        return result
    if isinstance(stmt, _ast.ReturnStmt):
        return [stmt.value] if stmt.value else []
    return []


class _Finding(str):
    """A static check's message, remembering where it was found.

    The checks read as they did when they answered with a plain string,
    and every caller that tests one or interpolates it still works.
    What is added is the position of the node the check objected to, so
    the diagnostic can point at it rather than name the function and
    leave the reader to search.

    A check with no particular node to blame builds one of these
    without a node, or returns a plain string; either way `pos` reads
    as None through getattr.
    """

    pos: tuple[int, int, int | None] | None

    def __new__(cls, message: str, node=None):
        finding = super().__new__(cls, message)
        finding.pos = getattr(node, "pos", None) if node is not None else None
        return finding


def _says_nothing(ret_type) -> bool:
    """Whether a signature promises no value at all.

    Leaving the return type off says what ∅ says, so the two read
    alike here: neither describes a value that could be matched on or
    carry an error type.
    """
    return not ret_type or ret_type == "\N{EMPTY SET}"


def _finding_pos(finding) -> tuple[int, int, int | None] | None:
    """The position a finding carries, or None for a plain message."""
    return getattr(finding, "pos", None)


def _node_pos(node) -> tuple[int, int, int | None] | None:
    """The position of an AST node, or None where it has none."""
    return getattr(node, "pos", None)


def _field_pos(struct_def, field_name):
    """Where a struct field's type was written.

    Falls back to the struct itself for a field the definition does not
    place — one named by a complaint that came from somewhere other
    than this struct's own text.
    """
    if field_name is not None:
        placed = getattr(struct_def, "field_positions", {}).get(field_name)
        if placed is not None:
            return placed
    return _node_pos(struct_def)


def _iter_ast(node, stop_at=()):
    """Yield every AST node reachable from node, itself included.

    Nodes listed in stop_at are yielded but not descended into, so a
    caller can treat them as boundaries and handle their contents on
    their own terms.  Iterative, with the field names cached per node
    class: the static checks walk every function's tree several times,
    and this walk is most of what loading a large program costs.
    """
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, (list, tuple)):
            stack.extend(reversed(n))
            continue
        if type(n).__module__ != "interp.ast":
            continue
        yield n
        if stop_at and isinstance(n, stop_at):
            continue
        fields = _fields_of(n)
        for name in reversed(fields):
            child = getattr(n, name, None)
            if child is not None:
                stack.append(child)


_FIELDS_CACHE: dict = {}


def _fields_of(node) -> tuple[str, ...]:
    """The names of what a node holds, however the node stores them."""
    cls = type(node)
    got = _FIELDS_CACHE.get(cls)
    if got is not None:
        return got
    if hasattr(node, "__dict__"):
        fields = tuple(vars(node))
    else:
        fields = tuple(getattr(cls, "__slots__", ()))
    _FIELDS_CACHE[cls] = fields
    return fields


def _propagated_error_type(expr, env) -> str | None:
    """The error type an expression can produce, when it is knowable.

    Returns None when the expression's error type cannot be determined
    without evaluating it, in which case no static claim is made.
    """
    if isinstance(expr, _ast.BinOp) and expr.op in ("\N{DIVISION SIGN}", "%"):
        # Division and remainder report failure as std.errors.
        return "std.errors"
    if isinstance(expr, _ast.FuncCall):
        try:
            callee = env.lookup(expr.name)
        except KeyError:
            return None
        ret_type = getattr(callee, "ret_type", None)
        if _says_nothing(ret_type):
            return None
        _, err = _split_optional_type(ret_type)
        return err or None
    return None


def _static_check_try(func_def, env) -> str | None:
    """Check every `?` in a function against its declared return type.

    `?` returns from the function it is written in when the value it is
    applied to is absent or failed, so that function has to be able to
    say so: its return type must be optional or expected.  When it is
    expected, the error being propagated has to be the error type it
    promises, since the caller will read it as that type.

    An optional return absorbs any error -- the detail is discarded and
    ∅ returned -- so nothing needs to match there.
    """
    return _check_try_in(func_def.body, func_def.ret_type, env)


def _check_try_in(body, ret_type, env, *, in_lambda: bool = False) -> str | None:
    """Check the `?` operators of one function or lambda body."""
    _, opt_err = _split_optional_type(ret_type) if ret_type else (None, None)
    where = "lambda" if in_lambda else "enclosing function"

    for node in _iter_ast(body, stop_at=(_ast.LambdaExpr,)):
        # A lambda is its own function: a ? inside one returns from the
        # lambda, so it is checked against the lambda's return type.
        if isinstance(node, _ast.LambdaExpr):
            nested = _check_try_in(node.body, node.ret_type, env,
                                   in_lambda=True)
            if nested is not None:
                return nested
            continue
        if not isinstance(node, _ast.TryUnwrap):
            continue
        if opt_err is None:
            return _Finding(
                f"? requires the {where} to return an optional or an "
                f"expected type, but it returns "
                f"'{ret_type or chr(8709)}'", node)
        if opt_err == "":
            continue
        source = _propagated_error_type(node.expr, env)
        if source is not None and source != opt_err:
            return _Finding(
                f"? propagates an error of type '{source}', but the "
                f"{where} returns errors of type '{opt_err}'", node)
    return None


# Builtin methods that answer with an optional.  A user-defined method of
# the same name suppresses the assumption rather than risking a wrong one.
_OPTIONAL_METHODS = frozenset({"next", "get", "pop"})

_ARM_PATTERN = {"some": "\N{THERE EXISTS}(...)", "none": "\N{EMPTY SET}",
                "err": "\N{THERE DOES NOT EXIST}(...)", "wildcard": "_"}
_ARM_SUBJECT = {"some": "a present value", "none": "\N{EMPTY SET}",
                "err": "a failed result"}
_SUBJECT_SHAPES = {"optional": {"some", "none"},
                   "expected": {"some", "err"},
                   "plain": {"some"}}
# What to say when an arm meets a subject that does not admit it.  The
# useful hint names the pattern that stands for the same idea in the
# subject's own shape; where the subject has no such pattern there is
# nothing helpful to add.
_WRONG_ARM_HINT = {
    ("optional", "err"): ", whose absence is \N{EMPTY SET}",
    ("expected", "none"): ", whose failure is \N{THERE DOES NOT EXIST}(e)",
}

_SUBJECT_NAME = {"optional": "an optional", "expected": "a result",
                 "plain": "a plain value"}


def _declared_param_type(name: str, func_def) -> str | None:
    """The type a parameter of this function was declared with.

    A parameter is where a type is written down.  A name bound from an
    expression carries whatever the expression produced instead, and
    nothing is claimed about it here.
    """
    if func_def is None:
        return None
    for param in func_def.params:
        param_name = param[0] if isinstance(param, tuple) else param
        param_type = param[1] if isinstance(param, tuple) else None
        if param_name == name and param_type is not None:
            return param_type
    pack = getattr(func_def, "pack_param", None)
    if pack is not None and pack[0] == name:
        # A pack is a list of arguments rather than one value, so its
        # element type says nothing about matching the pack itself.
        return None
    return None


def _declared_local_type(name: str, func_def) -> str | None:
    """The type a local binding of this name was declared with.

    A `let` that writes a type says as much about the name as a
    parameter does.  A name declared more than once with types that
    disagree is left alone: which one a match meets would depend on
    where it sits, and that is more than this reads.
    """
    if func_def is None:
        return None
    declared: set[str] = set()
    for node in _iter_ast(func_def.body, stop_at=(_ast.LambdaExpr,)):
        if isinstance(node, _ast.VarDef) and node.name == name \
                and node.type_annotation is not None:
            declared.add(node.type_annotation)
    return declared.pop() if len(declared) == 1 else None


def _kind_of_declared_type(type_name: str) -> str | None:
    """Classify a written type as a match subject.

    A sum type answers with its own name, since the arms name its
    alternatives.  Everything else is told apart by what the type
    says can be absent: `T?` admits ∅, `T!` admits a failure, and a
    type saying neither is a plain value.
    """
    if type_name is None or is_generic_type(type_name):
        return None
    if sum_type_alternatives(type_name) is not None:
        return type_name
    _, opt_err = _split_optional_type(type_name)
    if opt_err is None:
        return "plain"
    return "optional" if opt_err == "" else "expected"


def _arm_pattern(arm) -> str:
    """How an arm's pattern is written, for a diagnostic about it."""
    if arm.kind == "type":
        return f"'{arm.type_name}(...)'"
    return _ARM_PATTERN[arm.kind]


def _user_defines_method(name: str, env) -> bool:
    """Whether any struct in scope defines a method of this name."""
    for frame in env._frames:
        for value in frame.values():
            if isinstance(value, StructType) and name in value.methods:
                return True
    return False


def _match_subject_kind(expr, env, func_def=None) -> str | None:
    """Classify what a match subject can be: optional, expected, or plain.

    Returns None when it cannot be determined without running the
    program, in which case no static claim is made and the check falls to
    the evaluator.
    """
    # A name whose type is written down is classified by that type: a
    # sum type by its alternatives, and everything else by what the
    # type says can be absent.  This is what makes `match p` on a
    # parameter declared `i32?` answerable before anything runs.
    if isinstance(expr, _ast.VarRef):
        declared = (_declared_param_type(expr.name, func_def)
                    or _declared_local_type(expr.name, func_def))
        if declared is not None:
            kind = _kind_of_declared_type(declared)
            if kind is not None:
                return kind

    if isinstance(expr, (_ast.OptSome, _ast.NoneLit)):
        return "optional"
    if isinstance(expr, _ast.ExpErr):
        return "expected"
    if isinstance(expr, _ast.BinOp) and expr.op in ("\N{DIVISION SIGN}", "%"):
        return "expected"
    if isinstance(expr, _ast.FuncCall):
        try:
            callee = env.lookup(expr.name)
        except KeyError:
            return None
        ret_type = getattr(callee, "ret_type", None)
        if _says_nothing(ret_type):
            return None
        if sum_type_alternatives(ret_type) is not None:
            return ret_type
        _, opt_err = _split_optional_type(ret_type)
        if opt_err is None:
            return "plain"
        return "optional" if opt_err == "" else "expected"
    if isinstance(expr, _ast.MethodCall):
        if (expr.method in _OPTIONAL_METHODS
                and not _user_defines_method(expr.method, env)):
            return "optional"
    return None


def _check_one_match(node, env, func_def=None) -> str | None:
    """Check one match for unreachable and missing arms.

    Two kinds of mistake need no knowledge of the subject: a repeated
    pattern, and an arm written after `_`.  Both are arms that can never
    run, and saying so is always possible.

    The rest -- a pattern that does not belong to the subject's type, and
    a shape left unhandled -- needs the subject's type, and is checked
    only where that can be worked out.
    """
    # Two arms naming different alternatives are different patterns,
    # so a type arm is identified by the type it names.
    seen: set[str] = set()
    for index, arm in enumerate(node.arms):
        key = arm.type_name if arm.kind == "type" else arm.kind
        if key in seen:
            return _Finding(
                f"match repeats the {_arm_pattern(arm)} pattern; "
                f"the second one can never be reached", arm)
        seen.add(key)
        if arm.kind == "wildcard" and index != len(node.arms) - 1:
            # The arm that cannot run is the one after _, so that is
            # the one to point at.
            return _Finding(
                "match has arms after _, which can never be reached",
                node.arms[index + 1])

    subject = _match_subject_kind(node.subject, env, func_def)
    if subject is None:
        return None

    alternatives = sum_type_alternatives(subject)
    if alternatives is not None:
        for arm in node.arms:
            if arm.kind == "wildcard":
                continue
            if arm.kind != "type":
                return _Finding(
                    f"{_arm_pattern(arm)} cannot match '{subject}', "
                    f"which is {' | '.join(alternatives)}", arm)
            if arm.type_name not in alternatives:
                return _Finding(
                    f"'{arm.type_name}' is not an alternative of "
                    f"'{subject}', which is "
                    f"{' | '.join(alternatives)}", arm)
        if "wildcard" in seen:
            return None
        missing = [a for a in alternatives if a not in seen]
        if missing:
            return _Finding("match has no arm for "
                            + " or ".join(missing)
                            + "; add the missing pattern or a _ arm", node)
        return None

    shapes = _SUBJECT_SHAPES[subject]

    for arm in node.arms:
        if arm.kind == "wildcard" or arm.kind in shapes:
            continue
        # The hint points at the pattern the subject does admit, so it
        # is only worth giving where there is one.  A plain value
        # admits neither absence nor failure, and saying it has a
        # failure to be written some other way would misdirect.
        hint = _WRONG_ARM_HINT.get((subject, arm.kind), "")
        return _Finding(f"{_arm_pattern(arm)} cannot match "
                        f"{_SUBJECT_NAME[subject]}{hint}", arm)

    if "wildcard" in seen:
        return None
    missing = sorted(shapes - seen)
    if missing:
        return _Finding("match has no arm for "
                        + " or ".join(_ARM_SUBJECT[m] for m in missing)
                        + "; add the missing pattern or a _ arm", node)
    return None


def _placeholder_value(type_name: str, unit_spec, env):
    """A value standing for anything of a declared type.

    A static assertion over @typeof, @sizeof, or @unitof asks about the
    type, so any value of that type answers it.  Only types that can be
    stood for confidently are built; anything else returns None and the
    assertion is left to run.
    """
    from interp.value import mk_int, mk_float, mk_bool, mk_str, UnitValue
    from interp.units import eval_unit_formula
    resolved = validate_type(type_name) and resolve_type_alias(type_name)
    if not resolved:
        return None
    if resolved in _TYPE_BITS:
        value = mk_int(0, resolved)
    elif resolved == "int":
        value = mk_int(0)
    elif resolved in FLOAT_TYPES:
        value = mk_float(0.0, resolved)
    elif resolved == "bool":
        value = mk_bool(False)
    elif resolved == "str":
        value = mk_str("")
    else:
        return None
    if unit_spec is not None:
        value = UnitValue(value, eval_unit_formula(unit_spec))
    return value


_SHIFT_OPS = frozenset({"\N{LEFT-POINTING DOUBLE ANGLE QUOTATION MARK}",
                        "\N{RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK}",
                        "<<", ">>"})


def _static_shift_check(node, checker) -> str | None:
    """Report a shift whose count is already too far to be written.

    The bound depends on the type shifted and on the count, so where
    the count is a constant and the type is declared, the answer is
    settled before anything runs.  Saying so then is better than
    handing back an error value the program has to deal with.

    Anything not settled that way is left alone, and the shift reports
    at runtime as before.
    """
    from interp.eval import _is_const_expr
    if not _is_const_expr(node.right):
        return None
    try:
        result = checker.eval_expr(node)
    except Exception:
        return None
    if not isinstance(result, ExpectedValue) or not result.is_err():
        return None
    err = result.err_value
    if not (isinstance(err, EnumValue)
            and err.enum_type.name == "errors"
            and err.enum_type.values_to_names.get(err.value) ==
            "shift_out_of_range"):
        return None
    return _Finding(
        "this shift moves every value bit out, so it can only fail; "
        "the count is too far for the type shifted", node)


def _static_assert_check(func_def, env) -> str | None:
    """Decide the static assertions a function's declarations settle.

    An assertion over the type of a name is answerable without running
    anything, since the declaration says what the type is.  Checking it
    here means a wrong one is reported whether or not the function is
    ever called.

    Assertions naming anything that cannot be stood for are left alone,
    to be checked when the function runs.
    """
    known = Env()
    for param in func_def.params:
        param_name = param[0] if isinstance(param, tuple) else param
        param_type = param[1] if isinstance(param, tuple) else None
        if param_type is None:
            continue
        value = _placeholder_value(param_type,
                                   func_def.param_units.get(param_name), env)
        if value is not None:
            known.define(param_name, value)

    checker = Evaluator(known)
    checker._comptime_vars = {n for n, _ in
                              [(p[0], None) if isinstance(p, tuple) else (p, None)
                               for p in func_def.params]}
    for node in _iter_ast(func_def.body):
        if isinstance(node, _ast.VarDef) and node.type_annotation is not None:
            if isinstance(node.init_expr, _ast.ArrayAlloc):
                # An allocation keeps its shape in the brackets rather
                # than in the annotation, so the annotation alone names
                # the element type.  Standing for the value with one
                # element would answer what the array occupies with what
                # one of its numbers does.
                continue
            value = _placeholder_value(node.type_annotation, node.unit_spec, env)
            if value is not None:
                known.define(node.name, value)
            continue
        if isinstance(node, _ast.BinOp) and node.op in _SHIFT_OPS:
            problem = _static_shift_check(node, checker)
            if problem is not None:
                return problem
            continue
        if not isinstance(node, (_ast.StaticAssert, _ast.StaticAssertEq)):
            continue
        try:
            checker.eval_expr(node)
        except TypeError as e:
            if "static_assert" in str(e) and "failed" in str(e):
                return _Finding(str(e), node)
        except Exception:
            # Not answerable from declarations alone; it runs instead.
            pass
    return None


def _literal_array_shape(expr) -> list[int | None] | None:
    """The shape of an expression that is written out as an array.

    Only a literal answers this: its brackets say the shape without
    anything having to run.  A level whose rows are not all literals of
    one length has no single extent to report, so it reports None and
    the walk stops, as a runtime shape does.

    Returns None for an expression that is not a literal array.
    """
    if not isinstance(expr, _ast.ArrayLit):
        return None
    dims: list[int | None] = [len(expr.elements)]
    rows = expr.elements
    while rows and all(isinstance(r, _ast.ArrayLit) for r in rows):
        widths = {len(r.elements) for r in rows}
        if len(widths) != 1:
            dims.append(None)
            break
        dims.append(widths.pop())
        rows = [e for r in rows for e in r.elements]
    return dims


def _returned_exprs(func_def):
    """The expressions a function hands back.

    An explicit `return` names one, and a body ending in an expression
    hands that one back.  A lambda's returns are its own, so the walk
    stops at one rather than crediting them to the function around it.
    """
    for node in _iter_ast(func_def.body, stop_at=(_ast.LambdaExpr,)):
        if isinstance(node, _ast.ReturnStmt) and node.value is not None:
            yield node.value
    body = func_def.body
    if isinstance(body, list) and body and isinstance(body[-1], _ast.ExprStmt):
        yield body[-1].expr


# What is always a container, whatever it is written over: joining two
# of them, reshaping into one, and asking something of each.
_ALWAYS_A_CONTAINER = (_ast.MapExpr, _ast.ReshapeExpr)


# What a written-down value is, where the writing says it.  A number
# with no width stated settles on whatever is asked of it, so `int` and
# `float` are answers that agree with any other number.
_LITERAL_TYPES = {
    "StrLit": "str", "CharLit": "char", "BoolLit": "bool",
    "NoneLit": "\N{EMPTY SET}",
}

# The operators that answer a truth value whatever they are given.
_ANSWERS_A_TRUTH = frozenset({
    "=", "\N{NOT EQUAL TO}", "<", ">", "<=", ">=", "and", "or",
    "\N{ELEMENT OF}", "\N{SUBSET OF OR EQUAL TO}", "\N{SUBSET OF}",
    "\N{ALMOST EQUAL TO}", "\N{NOT ALMOST EQUAL TO}",
})

_UNWIDTHED = frozenset({"int", "float"})


def _static_type_of(expr, types: dict, structs: dict) -> str | None:
    """What an expression is, where the program says so.

    Enough to compare the two sides of a conditional: what is written
    down says what it is, a name says what its declaration said, and a
    comparison answers a truth value however it is reached.  Anything
    else answers None, which is what leaves a pair unjudged.
    """
    named = _LITERAL_TYPES.get(type(expr).__name__)
    if named is not None:
        return named
    if isinstance(expr, (_ast.IntLit, _ast.FloatLit)):
        return expr.width
    if isinstance(expr, _ast.VarRef):
        return types.get(expr.name)
    if isinstance(expr, _ast.GetAttr):
        return _field_type(expr, structs)
    if isinstance(expr, _ast.BinOp) and expr.op in _ANSWERS_A_TRUTH:
        return "bool"
    if isinstance(expr, _ast.UnaryOp) and expr.op in ("not",
                                                      "\N{NOT SIGN}"):
        return "bool"
    if isinstance(expr, _ast.IfExpr):
        one = _static_type_of(expr.then_expr, types, structs)
        other = _static_type_of(expr.else_expr, types, structs)
        return one if one == other else None
    return None


def _field_type(expr, structs: dict) -> str | None:
    """What a struct says one of its fields is."""
    if not (isinstance(expr, _ast.GetAttr)
            and isinstance(expr.obj, _ast.VarRef)):
        return None
    struct = structs.get(expr.obj.name)
    if struct is None:
        return None
    for field_name, field_type in struct.fields:
        if field_name == expr.attr:
            return field_type or None
    return None


def _types_agree(one: str, other: str) -> bool:
    """Whether two written types can be the one value a conditional is.

    A number with no width settles on what it is asked for, so it
    agrees with any other number.  Nothing agrees with an absent value
    but an absent value, since an optional is what holds both.  And two
    that disagree are still fine where a sum type says the two belong
    together, which is the whole of what a sum type is for.
    """
    if one == other:
        return True
    if is_generic_type(one) or is_generic_type(other):
        return True
    if "\N{EMPTY SET}" in (one, other) or one.endswith("?") \
            or other.endswith("?"):
        return True
    numeric = {"int", "float"} | set(_TYPE_BITS) | set(FLOAT_TYPES)
    if one in numeric and other in numeric \
            and (one in _UNWIDTHED or other in _UNWIDTHED):
        return True
    return a_sum_holds_both(one, other)


def _local_types(definition) -> dict:
    """What each local says it is, for the names that say it once.

    A name written twice with two types is two names to a reader and
    one to this walk, which has no scopes; leaving both out is what
    keeps it from reading one declaration against the other's use.
    """
    seen: dict[str, str | None] = {}
    twice: set[str] = set()
    for node in _iter_ast(definition):
        if not isinstance(node, _ast.VarDef) or not isinstance(node.name, str):
            continue
        if node.name in seen:
            twice.add(node.name)
        seen[node.name] = node.type_annotation
    return {name: written for name, written in seen.items()
            if written and name not in twice
            and not written.startswith("mut ")}


def _static_conditional_check(definition, structs: dict | None = None) -> str | None:
    """Refuse a conditional whose two sides cannot be the one value.

    Only what the program writes down is read, so a pair is judged only
    where both sides say what they are.  Where either says nothing the
    conditional is left alone -- it is one value at runtime whatever
    this could not work out.
    """
    structs = structs or {}
    types = _local_types(definition)
    for name, param_type in getattr(definition, "params", ()) or ():
        if param_type:
            types[_param_display(name)] = param_type
    for node in _iter_ast(definition):
        if not isinstance(node, _ast.IfExpr):
            continue
        one = _static_type_of(node.then_expr, types, structs)
        other = _static_type_of(node.else_expr, types, structs)
        if one is None or other is None or _types_agree(one, other):
            continue
        return _Finding(
            f"a conditional is one value, so its two sides say one type "
            f"between them; this one says {one} where the condition holds "
            f"and {other} where it does not", node)
    return None


def _field_rank(expr, structs: dict) -> int | None:
    """How deep a field's declared type says it is, where the struct is known.

    `self.v` is the case this exists for: the struct says what v is,
    and a name standing for a struct instance is what says which
    struct.  A name that stands for none, or a field the struct does
    not declare, says nothing.
    """
    if not (isinstance(expr, _ast.GetAttr)
            and isinstance(expr.obj, _ast.VarRef)):
        return None
    struct = structs.get(expr.obj.name)
    if struct is None:
        return None
    for field_name, field_type in struct.fields:
        if field_name == expr.attr:
            if not field_type or is_generic_type(field_type):
                return None
            base, _ = _split_optional_type(field_type)
            return declared_rank(resolve_type_alias(base if base
                                                    else field_type))
    return None


def _least_rank(expr, ranks: dict, structs: dict | None = None) -> int | None:
    """How many containers deep the expression is at least, where known.

    Threading is what makes this answerable without running anything: a
    listable operator handed a container answers a container, whatever
    the other operand is.  So a lower bound is enough -- the question
    being asked is only whether an array comes back where a scalar was
    promised.

    None where nothing about the expression says: a call to a function
    whose answer is not known here, a name that is not a parameter, a
    fold, anything else.  Saying nothing is what leaves a case to the
    check that meets the value itself.
    """
    structs = structs or {}
    if isinstance(expr, _ast.VarRef):
        return ranks.get(expr.name)
    if isinstance(expr, _ast.GetAttr):
        return _field_rank(expr, structs)
    if isinstance(expr, _ALWAYS_A_CONTAINER):
        return 1
    if isinstance(expr, _ast.ArrayLit):
        dims = _literal_array_shape(expr)
        return None if dims is None else len(dims)
    if isinstance(expr, _ast.BinOp) \
            and (expr.op in Evaluator._LISTABLE_BINOPS
                 or expr.op == "\N{DOUBLE PLUS}"):
        # Either operand being a container makes the answer one.
        sides = [_least_rank(expr.left, ranks, structs),
                 _least_rank(expr.right, ranks, structs)]
        deepest = [r for r in sides if r is not None and r >= 1]
        if deepest:
            return max(deepest)
        return None if None in sides else 0
    if isinstance(expr, _ast.UnaryOp) \
            and expr.op in Evaluator._LISTABLE_UNOPS:
        return _least_rank(expr.operand, ranks, structs)
    if isinstance(expr, _ast.IfExpr):
        # Whichever branch runs is the answer, so only what both say is
        # something this can say.
        sides = [_least_rank(expr.then_expr, ranks, structs),
                 _least_rank(expr.else_expr, ranks, structs)]
        if None in sides:
            return None
        return min(sides)
    return None


def _parameter_ranks(params) -> dict:
    """How deep each parameter's declared type says it is.

    Every parameter of a function states a type, so this is known for
    all of them -- except a generic, which stands for whatever it is
    handed and says nothing about how deep that is, and a lambda's,
    which may leave the type off altogether.
    """
    ranks: dict[str, int] = {}
    for name, param_type in params:
        if param_type is None or is_generic_type(param_type):
            continue
        base, _ = _split_optional_type(param_type)
        ranks[_param_display(name)] = declared_rank(
            resolve_type_alias(base if base else param_type))
    return ranks


def _static_return_check(func_def, structs: dict | None = None) -> str | None:
    """Refuse an array handed back where the return type names a scalar.

    A literal says its shape where it is written, and the signature
    says what the function returns, so the two disagreeing is settled
    before anything runs.  Saying so then reports it whether or not the
    function is ever called.

    Anything whose shape is not written down is left to run, where the
    same check meets the value itself.
    """
    return _return_shape_finding(getattr(func_def, "ret_type", None),
                                 func_def.params,
                                 _returned_exprs(func_def),
                                 structs=structs or {})


def _lambda_returns(lam):
    """The expressions a lambda hands back.

    A body that is one expression hands that one back; a body of
    statements hands back its last where that is an expression, and any
    return written inside it.  A lambda written inside a lambda is its
    own, so the walk stops at one.
    """
    body = lam.body
    if not isinstance(body, list):
        yield body
        return
    for node in _iter_ast(body, stop_at=(_ast.LambdaExpr,)):
        if isinstance(node, _ast.ReturnStmt) and node.value is not None:
            yield node.value
    if body and isinstance(body[-1], _ast.ExprStmt):
        yield body[-1].expr


def _static_lambda_return_check(definition, env=None,
                                structs: dict | None = None) -> str | None:
    """The same check for every lambda written inside a definition.

    A lambda states its own parameters and its own return type, so the
    question is the one a named function is asked and the answer is
    reached the same way.  The whole definition is walked rather than
    its body, so a lambda bound to a name, or written into a condition,
    is asked it too.
    """
    outer = structs or {}
    for node in _iter_ast(definition):
        if not isinstance(node, _ast.LambdaExpr):
            continue
        # A lambda's own struct-typed parameters stand for instances
        # too, alongside whatever the definition around it named.
        seen = dict(outer)
        if env is not None:
            for name, param_type in node.params:
                struct = _struct_type_named(param_type, env)
                if struct is not None:
                    seen[name] = struct
        finding = _return_shape_finding(node.ret_type, node.params,
                                        _lambda_returns(node),
                                        subject="a lambda's return type",
                                        structs=seen)
        if finding is not None:
            return finding
    return None


def _return_shape_finding(ret_type, params, returned,
                          subject: str = "return type",
                          structs: dict | None = None) -> str | None:
    """Whether what is handed back is an array where a scalar is promised."""
    if _says_nothing(ret_type):
        return None
    base, _ = _split_optional_type(ret_type)
    check = resolve_type_alias(base if base else ret_type)
    if not check or check == "\N{EMPTY SET}" or is_generic_type(check):
        return None
    if _parse_array_type(check) is not None:
        return None
    ranks = _parameter_ranks(params)
    for expr in returned:
        dims = _literal_array_shape(expr)
        if dims is not None:
            written = ",".join("" if d is None else str(d) for d in dims)
            return _Finding(
                f"{subject} is {ret_type}, which is not an array type, "
                f"but the body hands back {format_shape(dims)} elements; "
                f"an array type says its shape, as "
                f"'{check}[{written}]'", expr)
        deep = _least_rank(expr, ranks, structs)
        if deep is not None and deep >= 1:
            # An array type of no stated extent is written with a
            # comma for each dimension past the first.
            shape = "[" + "," * (deep - 1) + "]"
            return _Finding(
                f"{subject} is {ret_type}, which is not an array type, "
                f"but the body hands back an array: an operator handed one "
                f"answers one for each of what it holds, so this is "
                f"'{check}{shape}'", expr)
    return None


def _static_check_match(func_def, env) -> str | None:
    """Check every match in a function, lambdas included."""
    for node in _iter_ast(func_def.body):
        if isinstance(node, _ast.MatchStmt):
            problem = _check_one_match(node, env, func_def)
            if problem is not None:
                return problem
    return None


def _modified_names(body) -> set[str]:
    """Names a body may change, by any route the language offers.

    Deliberately generous: a name is counted as modified when there is
    any plausible way the code could change it.  A warning that fires
    where nothing is wrong is worse than one that stays quiet, so
    anything uncertain counts as a modification.
    """
    modified: set[str] = set()

    def walk(node):
        """Like _iter_ast, but yields the tuples statements are encoded as."""
        if isinstance(node, list):
            for item in node:
                yield from walk(item)
            return
        if isinstance(node, tuple):
            yield node
            for item in node:
                yield from walk(item)
            return
        if type(node).__module__ != "interp.ast":
            return
        yield node
        for name in _fields_of(node):
            yield from walk(getattr(node, name, None))

    def base_of(expr):
        while isinstance(expr, (_ast.Subscript, _ast.SliceAccess,
                                _ast.MultiSlice, _ast.GetAttr)):
            expr = expr.obj
        return expr.name if isinstance(expr, _ast.VarRef) else None

    for node in walk(body):
        # x ← v, x[i] ← v, x.f ← v
        if isinstance(node, tuple):
            if len(node) == 3 and node[0] in ("assign_stmt", "assign"):
                target = node[1]
                name = target if isinstance(target, str) else base_of(target)
                if name is not None:
                    modified.add(name)
            elif len(node) == 4 and node[0] == "const_assign":
                modified.add(node[1])
            continue
        # x.push(...) and the other methods that change an array; a
        # method of a struct may take &mut self and write through it,
        # which cannot be seen from here, so any method not known to
        # only read counts as a modification -- generous, as above.
        if isinstance(node, _ast.MethodCall):
            if node.method not in _KNOWN_READONLY_METHODS:
                name = base_of(node.obj)
                if name is not None:
                    modified.add(name)
        # &x at a call site: the callee may write through it
        elif isinstance(node, _ast.RefExpr):
            modified.add(node.name)
        # foreach e := &mut x
        elif isinstance(node, _ast.BorrowExpr) and node.is_mut:
            name = base_of(node.expr)
            if name is not None:
                modified.add(name)
        # (dims ⍴ x): the result shares x's storage and inherits its
        # access, so writing through it writes x.
        elif isinstance(node, _ast.ReshapeExpr):
            name = base_of(node.data)
            if name is not None:
                modified.add(name)

    return modified


def _reshape_source_is_mutable(expr, mutable_names: set[str]) -> bool:
    """Whether a reshape draws its access from a mutable binding."""
    inner = expr.data
    while isinstance(inner, _ast.ReshapeExpr):
        inner = inner.data
    return isinstance(inner, _ast.VarRef) and inner.name in mutable_names


def _redundant_return_type_warning(func_def) -> list[tuple[str, tuple | None]]:
    """Point out a return type that repeats what saying nothing says.

    A signature with no return type hands nothing back, so writing ∅
    adds no information.  It is worth saying because the two spellings
    invite a reader to look for a difference between them.

    A generic return type is left alone even where it settles on ∅: the
    signature wrote a type variable, which says the caller decides, and
    that is not the same claim.  A lambda is left alone too, since one
    has to state a return type and ∅ is the only way to say this.
    """
    if getattr(func_def, "ret_type_pos", None) is None:
        return []
    if func_def.ret_type != "\N{EMPTY SET}":
        return []
    return [("a return type of ∅ says what leaving it off says; "
             "the shorter form is the one to use",
             func_def.ret_type_pos)]


# What the standard library never comes back from.  These are not
# functions the language declares, so they cannot carry the attribute;
# naming them here is what stands in for it.
_NORETURN_STD = frozenset({"exit", "abort"})


def _stmt_pos(stmt):
    """Where a statement was written.

    A statement that only holds an expression takes the expression's
    place, since that is the text the reader sees.
    """
    pos = _node_pos(stmt)
    if pos is None and isinstance(stmt, _ast.ExprStmt):
        return _node_pos(stmt.expr)
    return pos


def _never_returns(node, env) -> bool:
    """Whether a statement is one control does not come back from.

    A return leaves the function, and a call to something marked
    @noreturn leaves it too -- that is the whole of what the attribute
    says, and the whole of what makes what follows unreachable.
    """
    if isinstance(node, (_ast.ReturnStmt, _ast.BreakStmt,
                         _ast.ContinueStmt)):
        return True
    expr = node.expr if isinstance(node, _ast.ExprStmt) else node
    if isinstance(expr, _ast.MethodCall):
        # std.exit and std.abort, which the library cannot annotate.
        return (isinstance(expr.obj, _ast.VarRef) and expr.obj.name == "std"
                and expr.method in _NORETURN_STD)
    if isinstance(expr, _ast.FuncCall):
        try:
            called = env.lookup(expr.name)
        except KeyError:
            return False
        return bool(getattr(called, "is_noreturn", False))
    return False


def _unreachable_warnings(func_def, env) -> list[tuple[str, tuple | None]]:
    """Find statements nothing can reach.

    A statement after one that does not come back is written to be run
    and never will be, which is either a leftover or a mistake about
    what the line above does.  Reported as a warning: the program is
    well-formed, and it may be mid-edit.

    Only the first of a run is reported -- the rest are unreachable for
    the same reason, and saying so once says it.
    """
    warnings: list[tuple[str, tuple | None]] = []

    def walk(body):
        if not isinstance(body, list):
            return
        for index, stmt in enumerate(body):
            if _never_returns(stmt, env) and index + 1 < len(body):
                after = body[index + 1]
                warnings.append((
                    "this statement cannot be reached: the one above it "
                    "does not come back",
                    _stmt_pos(after)))
            for attr in ("body", "cons", "alt"):
                walk(getattr(stmt, attr, None))
            for arm in getattr(stmt, "arms", ()) or ():
                walk(getattr(arm, "body", None))
    walk(func_def.body)
    return warnings


def _unused_loop_label_warnings(func_def) -> list[tuple[str, tuple | None]]:
    """Find loop names nothing inside the loop takes.

    A name exists to be written after a break or a continue.  One that
    nothing takes says the loop is left from within when it is not,
    which is a reader's mistake waiting to happen -- and it is usually
    a leftover from a statement that was moved or deleted.  Reported as
    a warning: the program is well-formed and may be mid-edit.

    A lambda body is a boundary here as it is everywhere else: a break
    written inside one cannot leave a loop outside it, so it does not
    count as taking the name.
    """
    warnings: list[tuple[str, tuple | None]] = []

    def takers(body) -> set[str]:
        """The names break and continue take anywhere within a body."""
        taken: set[str] = set()
        for node in _iter_ast(body, stop_at=(_ast.LambdaExpr,)):
            if isinstance(node, (_ast.BreakStmt, _ast.ContinueStmt)) \
                    and node.label is not None:
                taken.add(node.label)
        return taken

    def walk(body):
        if not isinstance(body, list):
            return
        for stmt in body:
            if isinstance(stmt, (_ast.WhileStmt, _ast.ForEachStmt)) \
                    and stmt.label is not None \
                    and stmt.label not in takers(stmt.body):
                warnings.append((
                    f"the loop is named '{stmt.label}' and nothing inside "
                    f"it takes the name; a break or a continue reaches an "
                    f"outer loop by naming it",
                    stmt.label_pos))
            for attr in ("body", "cons", "alt"):
                walk(getattr(stmt, attr, None))
            for arm in getattr(stmt, "arms", ()) or ():
                walk(getattr(arm, "body", None))

    walk(func_def.body)
    # A lambda at any depth is walked on its own, since walk descends
    # statements and a lambda is written inside an expression.
    for node in _iter_ast(func_def.body):
        if isinstance(node, _ast.LambdaExpr) and isinstance(node.body, list):
            walk(node.body)
    return warnings


def _unused_mut_warnings(func_def) -> list[tuple[str, tuple | None]]:
    """Find mut bindings and parameters the function never modifies.

    A binding marked mut promises that it changes; one that does not is
    either a leftover from code that used to change it or a signal the
    reader will trust and be wrong about.  Either way the mut says
    something untrue, so it is worth pointing out -- as a warning, since
    the program is well-formed and may be mid-edit.
    """
    modified = _modified_names(func_def.body)
    warnings: list[tuple[str, tuple | None]] = []

    # Names this function can see to be mutable, for judging whether a
    # reshape binding inherits mut and so does not need to repeat it.
    mutable_names = set(func_def.param_muts)
    for node in _iter_ast(func_def.body):
        if isinstance(node, _ast.VarDef) and not node.is_const:
            mutable_names.add(node.name)

    for name in func_def.params:
        param_name = name[0] if isinstance(name, tuple) else name
        if param_name in func_def.param_muts and param_name not in modified:
            warnings.append((
                f"parameter '{param_name}' is declared mut but is never "
                f"modified",
                func_def.param_positions.get(param_name)))

    # A statement the programmer marked with @expect handles its own
    # diagnostics, so its warning is left for that rather than reported.
    marked = {id(node.stmt) for node in _iter_ast(func_def.body)
              if isinstance(node, _ast.ExpectStmt)}

    for node in _iter_ast(func_def.body):
        if isinstance(node, _ast.DestructureDef) and not node.is_const:
            for name in _destructured_names(node.names):
                if name == DISCARD_NAME or name in modified:
                    continue
                message = f"'{name}' is declared mut but is never modified"
                if id(node) in marked:
                    node.static_warnings = (
                        list(getattr(node, "static_warnings", ())) + [message])
                else:
                    warnings.append((message, getattr(node, "pos", None)))
            continue
        if not isinstance(node, _ast.VarDef) or node.is_const:
            continue
        if node.name == DISCARD_NAME:
            continue
        # A reshape binding without a type of its own takes its access
        # from the source, so repeating mut states what is already true.
        # Only when the source is a binding this function can see to be
        # mutable: a reshape of a literal has nothing to inherit from,
        # and one of an immutable source is an error rather than a
        # redundancy.
        if (node.type_annotation is None
                and isinstance(node.init_expr, _ast.ReshapeExpr)
                and _reshape_source_is_mutable(node.init_expr, mutable_names)):
            message = (f"'{node.name}' is declared mut, but a reshape already "
                       f"carries the access of what it was built from; "
                       f"naming a full type is what would change it")
            if id(node) in marked:
                node.static_warnings = [message]
            else:
                warnings.append((message, getattr(node, "pos", None)))
            continue
        if node.name in modified:
            continue
        message = f"'{node.name}' is declared mut but is never modified"
        if id(node) in marked:
            # Read back by the evaluator when the @expect runs.
            node.static_warnings = [message]
            continue
        warnings.append((message, getattr(node, "pos", None)))
    return warnings


# std calls that write where the rest of the program can see it.  A
# function making one is doing something its signature has to admit to.
_STD_OUTPUT_CALLS = frozenset({"print", "println"})


def _struct_type_named(type_name, env) -> StructType | None:
    """The struct a written type names, or None where it names none.

    A parameter may be written as a reference or as mut, and neither
    changes which struct the name stands for, so both are stripped
    before the name is looked up.
    """
    if not type_name:
        return None
    base = type_name.strip()
    for prefix in ("&mut ", "&", "mut "):
        if base.startswith(prefix):
            base = base[len(prefix):].strip()
    try:
        found = env.lookup(resolve_type_alias(base))
    except KeyError:
        return None
    return found if isinstance(found, StructType) else None


def _struct_vars_of(func_def, env, self_type=None) -> dict[str, StructType]:
    """The names in a function that stand for a struct instance.

    Enough to resolve `x.method()` back to the method it calls: the
    parameters that say a struct type, the locals initialized from
    something whose struct type is knowable, and, inside an impl block,
    self.  A name whose type cannot be worked out is simply absent, and
    a call through it is left unresolved rather than guessed at.
    """
    found: dict[str, StructType] = {}
    if self_type is not None:
        found["self"] = self_type
    for param in func_def.params:
        name, type_name = param if isinstance(param, tuple) else (param, None)
        struct = _struct_type_named(type_name, env)
        if struct is not None:
            found[name] = struct
    for node in _iter_ast(func_def.body):
        if not isinstance(node, ASTVarDef):
            continue
        struct = _struct_type_named(node.type_annotation, env)
        if struct is None:
            struct = _infer_struct_type(node.init_expr, env, found)
        if struct is not None:
            found[node.name] = struct
    return found


def _called_func(expr, env, struct_vars) -> FuncValue | None:
    """The function a call expression reaches, when that is knowable.

    Answers None for anything the interpreter provides itself and for a
    call through a name whose type is not written down: neither carries
    the declarations these checks read, so nothing is claimed about it.
    """
    if isinstance(expr, _ast.FuncCall):
        try:
            found = env.lookup(expr.name)
        except KeyError:
            return None
        return found if isinstance(found, FuncValue) else None
    if isinstance(expr, _ast.MethodCall):
        struct = None
        if isinstance(expr.obj, _ast.VarRef):
            struct = struct_vars.get(expr.obj.name)
            if struct is None:
                try:
                    found = env.lookup(expr.obj.name)
                except KeyError:
                    found = None
                if isinstance(found, StructType):
                    struct = found
        if struct is None:
            struct = _infer_struct_type(expr.obj, env, struct_vars)
        if struct is None:
            return None
        return struct.methods.get(expr.method)
    return None


class _Span:
    """A position to point a diagnostic at where no one node holds it."""

    def __init__(self, pos):
        self.pos = pos


def _call_site(expr):
    """What a diagnostic about a call should point at.

    A method call records where its dot was written, which on its own
    reads as a complaint about the dot.  The call is the receiver, the
    dot, and the name, so the three are underlined together.
    """
    if not isinstance(expr, _ast.MethodCall):
        return expr
    dot = getattr(expr, "pos", None)
    obj = getattr(expr.obj, "pos", None)
    if dot is None or obj is None or obj[0] != dot[0]:
        return expr
    return _Span((obj[0], obj[1], dot[2] + len(expr.method)))


def _std_output_call(expr) -> str | None:
    """The name of the std output call an expression makes, if any."""
    if (isinstance(expr, _ast.MethodCall)
            and isinstance(expr.obj, _ast.VarRef)
            and expr.obj.name == "std"
            and expr.method in _STD_OUTPUT_CALLS):
        return f"std.{expr.method}"
    return None


def _static_purity_check(func_def, env, struct_vars) -> str | None:
    """Refuse a function with a side effect its signature does not admit.

    Writing to the program's output is a side effect, and so is calling
    something that has one.  Either way the effect is part of what the
    function is, so it is written at the definition rather than left
    for a reader to find by following the calls.

    A function already marked @impure has said so and is left alone.
    """
    if func_def.is_impure:
        return None
    for node in _iter_ast(func_def.body):
        written = _std_output_call(node)
        if written is not None:
            return _Finding(
                f"{written} writes where the rest of the program can see "
                f"it; a function that calls it says @impure",
                _call_site(node))
        callee = _called_func(node, env, struct_vars)
        if callee is not None and callee.is_impure:
            return _Finding(
                f"'{callee.name}' is @impure, so a function that calls it "
                f"says @impure too", _call_site(node))
    return None


def _has_declared_effect(expr, env, struct_vars) -> bool:
    """Whether an expression does something besides produce a value.

    A call the checks cannot resolve is taken to have an effect: what
    it does is not written down anywhere they can read, and claiming a
    statement is pointless is only worth doing when it is certain.  A
    call that is resolved says for itself, with @impure.  `?` hands
    control back to the caller, and a static assertion is checked for
    its own sake, so both are effects of their own.
    """
    for node in _iter_ast(expr):
        if isinstance(node, (_ast.TryUnwrap, _ast.StaticAssert,
                             _ast.StaticAssertEq)):
            return True
        if not isinstance(node, (_ast.FuncCall, _ast.MethodCall)):
            continue
        callee = _called_func(node, env, struct_vars)
        if callee is None or callee.is_impure:
            return True
    return False


def _dropped_value_finding(expr, env, struct_vars) -> str | None:
    """What a statement whose value goes nowhere should be told.

    A function that hands back a value is called for that value, so a
    call whose result nothing reads is either a mistake or a line that
    could be deleted.  The same holds for an expression that is not a
    call at all: it computes something and drops it.

    Nothing is said where the statement has an effect of its own --
    that is what the statement was for, and the value is beside the
    point.
    """
    if _has_declared_effect(expr, env, struct_vars):
        return None
    if isinstance(expr, _ast.NoneLit):
        # ∅ is what a body writes when it does nothing.  There is no
        # value there to go unread, so there is nothing to report.
        return None
    if isinstance(expr, (_ast.FuncCall, _ast.MethodCall)):
        callee = _called_func(expr, env, struct_vars)
        if callee is None or _says_nothing(callee.ret_type):
            return None
        return _Finding(
            f"the result of '{callee.name}' is not used; a function that "
            f"hands back a value is called for it, so write '_ ← …' where "
            f"the value is meant to be dropped", _call_site(expr))
    return _Finding(
        "the value of this statement is not used; it computes something "
        "and nothing reads it", expr)


def _check_unused_values(stmts, env, struct_vars,
                         keeps_value: bool) -> str | None:
    """Look through a block for statements whose value goes nowhere.

    keeps_value says whether the last statement of this block is what
    the block hands back.  A function body hands back its last
    statement, and so do the arms of a match and the body of a catch
    standing in that position; the body of an if, a while, or a foreach
    hands back nothing, so every statement in one is checked.
    """
    for index, stmt in enumerate(stmts):
        finding = _check_one_unused_value(
            stmt, env, struct_vars,
            keeps_value and index == len(stmts) - 1)
        if finding is not None:
            return finding
    return None


def _check_one_unused_value(stmt, env, struct_vars,
                            in_value_position: bool) -> str | None:
    """Check one statement, and the blocks it holds, for a dropped value."""
    if isinstance(stmt, _ast.ExpectStmt):
        # The statement was marked as drawing a diagnostic, so the
        # finding is handed to the @expect rather than reported.
        inner = _check_one_unused_value(stmt.stmt, env, struct_vars,
                                        in_value_position)
        if inner is not None:
            stmt.stmt.static_errors = (
                list(getattr(stmt.stmt, "static_errors", ())) + [str(inner)])
        return None
    if isinstance(stmt, _ast.ExprStmt):
        if in_value_position:
            return None
        return _dropped_value_finding(stmt.expr, env, struct_vars)
    if isinstance(stmt, _ast.IfStmt):
        finding = _check_unused_values(stmt.cons, env, struct_vars, False)
        if finding is not None:
            return finding
        alt = stmt.alt
        while alt is not None:
            finding = _check_unused_values(alt[1], env, struct_vars, False)
            if finding is not None:
                return finding
            alt = alt[2] if len(alt) == 3 else None
        return None
    if isinstance(stmt, (_ast.WhileStmt, _ast.ForEachStmt)):
        return _check_unused_values(stmt.body, env, struct_vars, False)
    if isinstance(stmt, _ast.MatchStmt):
        for arm in stmt.arms:
            finding = _check_unused_values(arm.body, env, struct_vars,
                                           in_value_position)
            if finding is not None:
                return finding
        return None
    if isinstance(stmt, _ast.CatchStmt):
        return _check_unused_values(stmt.body, env, struct_vars,
                                    in_value_position)
    return None


def _static_unused_value_check(func_def, env, struct_vars) -> str | None:
    """Find a statement in a function whose value nothing reads.

    The last statement of a body is left to _trailing_value_warnings:
    where the signature hands something back it is the return value,
    and where it does not the mistake is likely the missing return type
    rather than the statement, which is a warning rather than an error.
    A lambda hands back its last statement the same way, so one written
    inside this function is walked on those terms rather than as part
    of the block holding it.
    """
    finding = _check_unused_values(func_def.body, env, struct_vars, True)
    if finding is not None:
        return finding
    for node in _iter_ast(func_def.body):
        if isinstance(node, _ast.LambdaExpr) and isinstance(node.body, list):
            finding = _check_unused_values(node.body, env, struct_vars, True)
            if finding is not None:
                return finding
    return None


def _trailing_value_warning(body, env, struct_vars,
                            warnings: list[tuple[str, tuple | None]]):
    """Report a body that ends in a value its signature does not hand back.

    A body ending in an expression is how a function returns one, but
    only where the signature says something comes back.  Where it says
    nothing, the last statement is not a return value and what it
    computes goes nowhere -- most often because the return type was
    left off by mistake.

    A warning rather than an error: the program is well-formed, the
    interpreter does pass the value to a caller that reads it, and the
    fix is a signature rather than the statement being complained
    about.
    """
    if not isinstance(body, list) or not body:
        return
    last = body[-1]
    marked = isinstance(last, _ast.ExpectStmt)
    stmt = last.stmt if marked else last
    if not isinstance(stmt, _ast.ExprStmt):
        return
    if _dropped_value_finding(stmt.expr, env, struct_vars) is None:
        return
    message = ("the value of this statement is not used; the signature "
               "hands nothing back, so the last statement is not a return "
               "value; name a return type, or write "
               "'_ \N{LEFTWARDS ARROW} \N{HORIZONTAL ELLIPSIS}' to drop "
               "the value")
    if marked:
        # Read back by the evaluator when the @expect runs.
        stmt.static_warnings = (
            list(getattr(stmt, "static_warnings", ())) + [message])
        return
    warnings.append((message, _node_pos(stmt.expr)))


def _trailing_value_warnings(func_def, env,
                             struct_vars) -> list[tuple[str, tuple | None]]:
    """Every body in a function that ends in a value nothing hands back."""
    warnings: list[tuple[str, tuple | None]] = []
    if _says_nothing(func_def.ret_type):
        _trailing_value_warning(func_def.body, env, struct_vars, warnings)
    for node in _iter_ast(func_def.body):
        if isinstance(node, _ast.LambdaExpr) and _says_nothing(node.ret_type):
            _trailing_value_warning(node.body, env, struct_vars, warnings)
    return warnings


def _destructured_names(names) -> list[str]:
    """Every name a destructuring binds, nested ones included."""
    flat: list[str] = []
    for entry in names:
        if isinstance(entry, (list, tuple)):
            flat.extend(_destructured_names(entry))
        else:
            flat.append(entry)
    return flat


def _param_display(param_name) -> str:
    """How a parameter's name reads in a diagnostic."""
    if not isinstance(param_name, tuple):
        return param_name
    return "(" + ", ".join(_param_display(n) for n in param_name) + ")"


def _negated_literals(body) -> set[int]:
    """The integer literals a ⁻ is written against.

    A ⁻ against a literal is part of the literal rather than an
    operation on it, which is how the evaluator reads one, so the
    number to check is the negative one.  Without that the lowest
    value of every signed type would be unwritable: ⁻128i8 would have
    to hold 128 in an i8 on the way to holding ⁻128.
    """
    return {id(node.operand) for node in _iter_ast(body)
            if isinstance(node, _ast.UnaryOp) and node.op == "\N{SUPERSCRIPT MINUS}"
            and isinstance(node.operand, _ast.IntLit)}


def _param_pos(func_def, param_name):
    """Where a parameter was written, or the definition where it is not.

    A complaint about a parameter belongs at the parameter.  The
    definition's own position is the `fn`, which is where a reader
    starts looking rather than where the answer is.
    """
    return func_def.param_positions.get(param_name) or _node_pos(func_def)


def _needs_a_type(func_name: str, param_name: str) -> str:
    """Say that a parameter has to state what it takes.

    A signature is what a reader is given instead of the body, so a
    parameter that says nothing about what it takes leaves them the
    body to read.  Where the function genuinely takes whatever it is
    handed, a generic says that -- and says it once, so the type
    checker can hold the caller to it.
    """
    return (f"in {func_name}: parameter '{param_name}' states no type; "
            f"every parameter states one, and a generic such as T\N{APOSTROPHE} "
            f"says the function takes whatever it is handed")


def _static_noreturn_check(func_def) -> str | None:
    """Refuse a @noreturn function that says it hands something back.

    Stating a return type says what the caller receives, and @noreturn
    says the caller receives nothing because it is never reached again.
    A function cannot say both.
    """
    if not func_def.is_noreturn:
        return None
    if func_def.ret_type is not None \
            and func_def.ret_type != "\N{EMPTY SET}":
        return (f"{func_def.name} is @noreturn, so nothing comes back from "
                f"it, but its return type says {func_def.ret_type} does")
    return None


def _static_loop_check(func_def) -> str | None:
    """Refuse a break or a continue that names no loop it is in.

    Both say where execution goes, and where there is no such loop the
    statement says nothing -- so it is refused where it is written
    rather than left to be a jump to nowhere at the first run.  A
    lambda is a boundary: its body is a separate function, and a loop
    outside it is not one it can leave.
    """
    def walk(body, labels: tuple[str | None, ...]) -> str | None:
        if not isinstance(body, list):
            return None
        for stmt in body:
            found = visit(stmt, labels)
            if found is not None:
                return found
        return None

    def visit(stmt, labels: tuple[str | None, ...]) -> str | None:
        if isinstance(stmt, (_ast.BreakStmt, _ast.ContinueStmt)):
            word = "break" if isinstance(stmt, _ast.BreakStmt) else "continue"
            if not labels:
                return _Finding(f"{word} is written outside any loop, so "
                                f"there is no loop for it to act on", stmt)
            if stmt.label is not None and stmt.label not in labels:
                named = ", ".join(sorted(l for l in labels if l is not None))
                where = (f"the loops here are named {named}" if named
                         else "no loop here is named")
                return _Finding(f"{word} names the loop '{stmt.label}', "
                                f"which is not one it is inside; {where}",
                                stmt)
            return None
        if isinstance(stmt, (_ast.WhileStmt, _ast.ForEachStmt)):
            return walk(stmt.body, labels + (stmt.label,))
        for attr in ("body", "cons", "alt"):
            inner = getattr(stmt, attr, None)
            if isinstance(inner, list):
                found = walk(inner, labels)
                if found is not None:
                    return found
        for arm in getattr(stmt, "arms", ()) or ():
            found = walk(getattr(arm, "body", None), labels)
            if found is not None:
                return found
        return None

    found = walk(func_def.body, ())
    if found is not None:
        return found
    # A lambda body is a function of its own: a loop around the lambda
    # is not one its body can leave, so it starts with no loops in hand.
    for node in _iter_ast(func_def.body):
        if isinstance(node, _ast.LambdaExpr) \
                and isinstance(node.body, list):
            found = walk(node.body, ())
            if found is not None:
                return found
    return None


def _static_listable_check(func_def) -> str | None:
    """Refuse a @listable function that cannot be threaded.

    Threading compares what a parameter asks for with what it is
    handed, so every parameter has to say what it asks for, and the
    positions have to be fixed for there to be anything to compare.
    Where either is missing the attribute is refused where it is
    written rather than at the first call that goes wrong.
    """
    if not func_def.is_listable:
        return None
    name = func_def.name
    if not func_def.params and func_def.pack_param is None:
        return (f"{name} is @listable but takes no arguments; there is "
                f"nothing to thread over")
    if func_def.pack_param is not None:
        return (f"{name} is @listable, but it takes a parameter pack; "
                f"threading decides one position at a time, and a pack has "
                f"no fixed positions")
    for param_name, param_type in func_def.params:
        display = _param_display(param_name)
        # A parameter states a type wherever it is written, so there is
        # no untyped one left for threading to be unable to measure.
        if display in func_def.param_refs:
            return (f"{name} is @listable, but parameter '{display}' is "
                    f"taken by reference; threading hands the function one "
                    f"element of what the caller holds, which is not a place "
                    f"it can write back to")
    return None


def _static_chr_check(func_def) -> str | None:
    """Refuse .chr() on a number that is written down and negative.

    A character is numbered from zero, so a negative one names none.
    Where the number is a literal the answer is known without running
    anything, and a mistake known at the definition is reported there.
    """
    negated = _negated_literals(func_def.body)
    for node in _iter_ast(func_def.body):
        if not isinstance(node, _ast.MethodCall) or node.method != "chr":
            continue
        target = node.obj
        if isinstance(target, _ast.UnaryOp) and target.op == "\N{SUPERSCRIPT MINUS}":
            target = target.operand
            if not isinstance(target, _ast.IntLit):
                continue
            value = -target.value
        elif isinstance(target, _ast.IntLit):
            value = (-target.value if id(target) in negated
                     else target.value)
        else:
            continue
        if value < 0:
            return _Finding(
                f"chr: {value} is not a code point; a character is "
                f"numbered from 0", _call_site(node))
    return None


def _static_literal_check(func_def) -> str | None:
    """Refuse an integer literal the type its suffix names cannot hold.

    A suffix says what type a number is, so one the type cannot hold is
    a mistake in the literal, and the literal is where it is reported.
    Answering at the definition means it is found whether or not the
    code holding it ever runs, which is what the same check on a float
    literal already does.

    A literal without a suffix is untyped and arbitrary-precision, so
    there is nothing for it to fail to fit.
    """
    negated = _negated_literals(func_def.body)
    for node in _iter_ast(func_def.body):
        if not isinstance(node, _ast.IntLit):
            continue
        value = -node.value if id(node) in negated else node.value
        try:
            check_int(value, node.width or "int")
        except OverflowError as e:
            return _Finding(str(e), node)
    return None


def _static_check_moves(stmts: list, env,
                         moved: set[str] | None = None,
                         struct_vars: dict[str, StructType] | None = None,
                         ) -> str | None:
    """Detect use of struct variables after consuming method calls.

    Walks statements linearly.  Returns an error message or None.
    """
    if moved is None:
        moved = set()
    if struct_vars is None:
        struct_vars = {}

    for stmt in stmts:
        exprs = _stmt_top_exprs(stmt)
        for expr in exprs:
            for name in _expr_var_refs(expr):
                if name in moved:
                    return _Finding(f"use of moved value '{name}'",
                                    _var_ref_node(expr, name))

        if isinstance(stmt, ASTVarDef):
            st = _infer_struct_type(stmt.init_expr, env, struct_vars)
            if st is not None:
                struct_vars[stmt.name] = st
            moved.discard(stmt.name)

        for expr in exprs:
            moved |= _find_consuming_calls(expr, struct_vars)

        if isinstance(stmt, tuple) and len(stmt) == 3 and stmt[0] == "assign_stmt":
            target = stmt[1]
            if isinstance(target, _ast.VarRef):
                moved.discard(target.name)
                st = _infer_struct_type(stmt[2], env, struct_vars)
                if st is not None:
                    struct_vars[target.name] = st

        if isinstance(stmt, _ast.IfStmt):
            cond_refs = _expr_var_refs(stmt.cond)
            for name in cond_refs:
                if name in moved:
                    return _Finding(f"use of moved value '{name}'",
                                    _var_ref_node(stmt.cond, name))
            err = _static_check_moves(stmt.cons, env, moved.copy(), dict(struct_vars))
            if err:
                return err
            if stmt.alt is not None:
                # A branch is (cond, body) when nothing follows it and
                # (cond, body, rest) when further branches do; a plain
                # else has no condition.
                alt_cond, alt_cons, *alt_rest = stmt.alt
                if alt_cond is not None:
                    alt_stmt = _ast.IfStmt(alt_cond, alt_cons,
                                           alt_rest[0] if alt_rest else None)
                    err = _static_check_moves([alt_stmt], env, moved.copy(),
                                              dict(struct_vars))
                elif alt_cons:
                    err = _static_check_moves(alt_cons, env, moved.copy(),
                                              dict(struct_vars))
                if err:
                    return err

    return None


class DefinitionError(Exception):
    """A top-level definition could not be installed into the environment.

    `pos` is where in the source the objection lies, when the check
    that raised this knew.  Without one the message is printed on its
    own, as it always was.

    `warnings` are the ones found before the objection.  They are
    about definitions that were checked through, so they are still
    true and are reported rather than lost to the error.
    """

    def __init__(self, message, pos=None):
        super().__init__(message)
        self.pos = pos
        self.warnings: list[tuple[str, tuple | None]] = []
        if pos is not None:
            # The names extract_position reads, so the same position
            # reaches the prompt's diagnostic as well as the file's.
            self.line, self.col, self.end_col = pos


def _report_warnings(warnings, source: str, source_path: str) -> int:
    """Print warnings found while installing, in the order they were found.

    A position past the end of the text is shown as the message on its
    own: the REPL checks one entry at a time and numbers lines within
    it, so a warning from anywhere else has nothing here to point at.

    Returns how many were reported, which under -Werror is how many
    errors the program has.
    """
    level = diagnostic_level("warning")
    for message, position in warnings:
        if position is not None and position[0] <= source.count("\n") + 1:
            line, col, end_col = position
            print(format_diagnostic(source, source_path, line, col, message,
                                    end_col=end_col, level=level),
                  file=sys.stderr)
        else:
            print(f"{level}: {message}", file=sys.stderr)
    return len(warnings)


class LoadedProgram:
    """The parts of a program that installing its definitions produced."""

    def __init__(self):
        self.startup_func: FuncValue | None = None
        self.build_func: FuncValue | None = None
        self.standalone_tests: list[FuncValue] = []
        self.referenced_tests: dict[str, list[FuncValue]] = defaultdict(list)
        self.expect_funcs: list[ASTFuncDef] = []
        # (message, position) pairs found while installing definitions.
        self.warnings: list[tuple[str, tuple | None]] = []


def _trailing_semi_check(func_def) -> str | None:
    """A last expression with ';' where the function promises a value.

    The full language's trailing semicolon discards the value, so this
    function would answer ∅ there and the expression here -- the same
    program with two meanings.  The bootstrap refuses it instead.
    """
    ret = getattr(func_def, "ret_type", None)
    if ret in (None, "\N{EMPTY SET}"):
        return None
    body = func_def.body
    if not body:
        return None
    last = body[-1]
    if isinstance(last, _ast.ExprStmt) and getattr(last, "had_semi", False):
        return (f"'{func_def.name}' answers {ret}, but the trailing ';' "
                f"discards its last expression in the full language; drop "
                f"the ';' so the value is the answer, or return it")
    return None


def _int_type_range(type_name: str) -> tuple[int, int]:
    """The inclusive range of a sized integer type, by its name."""
    bits = int(type_name[1:]) if type_name[1:].isdigit() else 64
    if type_name.startswith("i"):
        return -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    return 0, (1 << bits) - 1


def install_definitions(definitions, env: Env, evaluator: Evaluator, *,
                        honor_start: bool = True,
                        redefine_vars: bool = False) -> LoadedProgram:
    """Install top-level definitions, keeping the warnings found on the way.

    A definition that is not well-formed stops the installation, but
    the warnings found before it are about definitions that were
    checked through, so they travel out with the error rather than
    being lost to it.
    """
    program = LoadedProgram()
    try:
        # Macros first and on their own: what the checks read is the
        # program with no macro left in it.
        try:
            macros = macro_collect(definitions)
            macro_expand(definitions, macros,
                         _macro_runner(macros, env, evaluator))
        except MacroError as e:
            raise DefinitionError(str(e), getattr(e, "pos", None)) from e
        _install_definitions(definitions, env, evaluator, program,
                             honor_start=honor_start,
                             redefine_vars=redefine_vars)
    except DefinitionError as e:
        e.warnings = program.warnings
        raise
    return program


def _macro_runner(macros: dict, env: Env, evaluator: Evaluator):
    """A way to run one macro, for the expansion pass to call.

    The macros written as functions, and the functions marked comptime,
    are installed in an environment of their own above the global one.
    So a macro can call another, and either can call a comptime
    function, and all of them can reach std, while nothing they define
    lands among the program's own names.

    The program's other functions are not there: they are installed
    after expansion, because expansion is what decides what they say.
    Marking a function comptime is what moves it to this side of that
    line.

    A macro written as rules needs none of this -- what it writes is
    decided by matching -- so the runner never sees one.
    """
    macro_env = Env(parent=env)
    made: dict[str, FuncValue] = {}
    # A comptime function is there before the program runs, which is
    # the whole of what the marker says and what lets a macro call it
    # -- including one that calls itself, since it is installed before
    # any of them is run.
    installed = [(name, defn) for name, defn in MACRO_COMPTIME.items()]
    installed += [(name, defn) for name, defn in macros.items()]
    for name, defn in installed:
        func = getattr(defn, "func", defn if isinstance(defn, ASTFuncDef)
                       else None)
        if func is None:
            # A macro written as rules has no function to install: what
            # it writes is decided by matching rather than by running.
            continue
        made[name] = FuncValue(
            func.name, func.params, func.body, macro_env, func.ret_type,
            func.is_replaceable, func.pack_param, func.param_units,
            func.is_impure, param_refs=func.param_refs,
            param_muts=func.param_muts, ret_unit=func.ret_unit,
            is_listable=func.is_listable, is_noreturn=func.is_noreturn,
            preconditions=func.preconditions,
            postconditions=func.postconditions)
        macro_env.define(name, made[name])

    def run(macro, args, call):
        try:
            return evaluator._call_user_func(made[macro.name], args)
        except MacroError:
            raise
        except Exception as e:
            raise MacroError(
                f"{macro.name} could not be run: "
                f"{_macro_reach(strip_position_prefix(str(e)))}",
                getattr(call, "pos", None)) from e

    return run


def _macro_reach(message: str) -> str:
    """Say why a name a macro reached for is not there, where that is why.

    A function the program defines is installed after expansion,
    because expansion is what decides what it says.  Reaching for one
    from a macro therefore finds nothing, and "undefined" is true but
    unhelpful: the name is defined, on the other side of a line the
    reader has to be told about.
    """
    found = re.search(r"undefined variable: '?([^'\s]+)'?", message)
    if found is None:
        return message
    name = found.group(1)
    if name not in MACRO_SEEN_FUNCTIONS or name in MACRO_COMPTIME:
        return message
    return (f"{name} is a function of the program, and a macro runs before "
            f"the program's functions are installed; write it as "
            f"`comptime fn {name}` to have it there in time")


def _install_definitions(definitions, env: Env, evaluator: Evaluator,
                         program: LoadedProgram, *,
                         honor_start: bool = True,
                         redefine_vars: bool = False) -> None:
    """Install top-level definitions into an environment.

    Definitions are installed in dependency order: type aliases, then
    variables, units, enums, structs, functions, and finally impl blocks,
    which need their struct to exist already.

    Args:
        definitions: the parsed top-level definitions.
        env: the environment to define names in.
        evaluator: used to evaluate variable initializers.
        program: collects the startup function, the tests, and the
            warnings found while installing.
        honor_start: whether an @start annotation designates the startup
            function.  False when the command line already named one.

    Raises:
        DefinitionError: when a definition is not well-formed.
    """
    # Named types first: an alias, a sum, a global, or a signature
    # may refer to any of them, and each may be declared below
    # whatever names it.

    # The measures a file names for itself register first: a global's
    # binding or a struct's field may state one, and both are installed
    # in the passes below.
    for defn in definitions:
        if isinstance(defn, ASTUnitDef):
            from interp.units import eval_unit_formula, register_user_unit, Unit
            from fractions import Fraction
            if defn.formula is not None:
                unit = eval_unit_formula(defn.formula)
                unit = Unit(unit.components, unit.factor, defn.name)
            else:
                unit = Unit({defn.name: 1}, Fraction(1), defn.name)
            register_user_unit(defn.name, unit)

    for defn in definitions:
        if isinstance(defn, ASTEnumDef):
            members: dict[str, int] = {}
            if defn.is_flag:
                next_val = 1
            else:
                next_val = 0
            for member_name, explicit_value in defn.members:
                if explicit_value is not None:
                    members[member_name] = explicit_value
                    if defn.is_flag:
                        next_val = explicit_value << 1
                    else:
                        next_val = explicit_value + 1
                else:
                    members[member_name] = next_val
                    if defn.is_flag:
                        next_val = next_val << 1
                    else:
                        next_val += 1
            if defn.is_flag and 0 not in members.values():
                members["nil"] = 0
            # Every member has to fit the type the values are stored
            # in -- u64 when none is named, so a negative member wants
            # a signed underlying type written down.
            stored_as = defn.underlying_type or "u64"
            lo, hi = _int_type_range(stored_as)
            for member_name, value in members.items():
                if not lo <= value <= hi:
                    raise DefinitionError(
                        f"enum '{defn.name}': member '{member_name}' is "
                        f"{value}, which does not fit {stored_as}, the "
                        f"type the values are stored in"
                        + ("" if defn.underlying_type else
                           " when none is named; a negative member wants "
                           "a signed underlying type, as 'enum "
                           f"{defn.name} : i64:'"),
                        getattr(defn, "pos", None))
            et = EnumType(defn.name, defn.underlying_type, members, defn.is_flag)
            register_enum_type(defn.name, defn.underlying_type, et)
            env.define(defn.name, et)

    for defn in definitions:
        if isinstance(defn, ASTStructDef):
            for field_name, field_type in defn.fields:
                try:
                    check_bootstrap_type(
                        field_type, f"struct '{defn.name}': field "
                                    f"'{field_name}'")
                except TypeError as e:
                    raise DefinitionError(
                        str(e), _field_pos(defn, field_name)) from None
            register_struct_type(defn.name)
            st = StructType(defn.name, defn.fields, repr_kind=defn.repr_kind,
                            field_units=getattr(defn, "field_units", None))
            env.define(defn.name, st)

    # Every struct and enum exists by now, so an alternative may be
    # declared below the sum type that names it.
    for defn in definitions:
        if isinstance(defn, _ast.SumTypeDef):
            for alt in defn.alternatives:
                if not validate_type(alt):
                    raise DefinitionError(
                        f"sum type '{defn.name}' names unknown type "
                        f"'{alt}' as an alternative", _node_pos(defn))
            register_sum_type(defn.name, defn.alternatives)

    for defn in definitions:
        if isinstance(defn, ASTTypeDef):
            if not validate_type(defn.target):
                raise DefinitionError(
                    f"type alias '{defn.name}' refers to unknown type "
                    f"'{defn.target}'", _node_pos(defn))
            try:
                check_bootstrap_type(defn.target,
                                     f"type alias '{defn.name}'")
            except TypeError as e:
                raise DefinitionError(str(e), _node_pos(defn)) from None
            register_type_alias(defn.name, defn.target)

    # Functions install before globals: a file may write its
    # functions in any order, and a global binding may call one
    # while it is being worked out.
    for defn in definitions:
        if isinstance(defn, ASTFuncDef):
            if defn.expect_annotations:
                program.expect_funcs.append(defn)
                continue

            if is_type_name(defn.name):
                raise DefinitionError(
                    f"'{defn.name}' names a type and cannot name a function",
                    _node_pos(defn))
            for param_name, param_type in defn.params:
                # A parameter naming a tuple's elements holds the names
                # in a tuple of its own, and each is checked as a name.
                for one in (_destructured_names(param_name)
                            if isinstance(param_name, tuple)
                            else [param_name]):
                    if is_type_name(one):
                        raise DefinitionError(
                            f"in {defn.name}: '{one}' names a type and "
                            f"cannot name a parameter",
                            _param_pos(defn, param_name))
                if param_type is None:
                    raise DefinitionError(
                        _needs_a_type(defn.name, _param_display(param_name)),
                        _param_pos(defn, param_name))
                try:
                    validate_param_type(
                        param_type, defn.name,
                        _param_display(param_name))
                except TypeError as e:
                    raise DefinitionError(
                        str(e), _param_pos(defn, param_name)) from None
            if defn.pack_param is not None:
                pp_name, pp_type = defn.pack_param
                if pp_type is None:
                    raise DefinitionError(
                        _needs_a_type(defn.name, pp_name),
                        _param_pos(defn, pp_name))
                try:
                    validate_param_type(pp_type, defn.name, pp_name)
                except TypeError as e:
                    raise DefinitionError(
                        str(e), _param_pos(defn, pp_name)) from None
            if defn.ret_type is not None:
                if not validate_type(defn.ret_type):
                    raise DefinitionError(
                        f"in {defn.name}: unknown return type "
                        f"'{defn.ret_type}'", _node_pos(defn))
                try:
                    check_bootstrap_type(defn.ret_type,
                                         f"in {defn.name}: return type")
                except TypeError as e:
                    raise DefinitionError(str(e), _node_pos(defn)) from None
            fv = FuncValue(defn.name, defn.params, defn.body, env, defn.ret_type,
                          defn.is_replaceable, defn.pack_param, defn.param_units,
                          defn.is_impure, param_refs=defn.param_refs,
                          param_muts=defn.param_muts, ret_unit=defn.ret_unit,
                          is_listable=defn.is_listable,
                          is_noreturn=defn.is_noreturn,
                          preconditions=defn.preconditions,
                          postconditions=defn.postconditions)
            env.define(defn.name, fv)

            if honor_start and defn.is_start:
                if program.startup_func is not None:
                    raise DefinitionError("multiple @start functions defined",
                                          _node_pos(defn))
                program.startup_func = fv

            if getattr(defn, "is_build", False):
                if program.build_func is not None:
                    raise DefinitionError("multiple @build functions defined",
                                          _node_pos(defn))
                if defn.params:
                    raise DefinitionError(
                        "the @build function takes no parameters",
                        _node_pos(defn))
                program.build_func = fv

            if defn.is_test:
                if defn.test_refs:
                    for ref in defn.test_refs:
                        program.referenced_tests[ref].append(fv)
                else:
                    program.standalone_tests.append(fv)


    for defn in definitions:
        if isinstance(defn, ASTVarDef):
            # A lambda written here states its own signature, so it is
            # asked what a function is asked.
            lambda_err = (_static_lambda_return_check(defn, env)
                          or _static_conditional_check(defn))
            if lambda_err is not None:
                raise DefinitionError(
                    f"in '{defn.name}': {lambda_err}",
                    _finding_pos(lambda_err) or _node_pos(defn))
            if defn.name == DISCARD_NAME:
                # Evaluated for its effects, then dropped; nothing is bound.
                evaluator.eval_expr(defn.init_expr)
                continue
            if defn.is_const and defn.type_annotation is not None and defn.type_annotation in FAST_TYPES:
                raise DefinitionError(
                    f"fast type '{defn.type_annotation}' cannot be used in "
                    f"let definition '{defn.name}'", _node_pos(defn))
            if not redefine_vars and defn.name in env._frames[0]:
                # A file defines a name once; a second let is a mistake
                # rather than an update.  The REPL is the one place a
                # definition may be replaced, entry by entry.
                raise DefinitionError(
                    f"'{defn.name}' is already defined; a file defines a "
                    f"name once (at the REPL a new let replaces the old)",
                    _node_pos(defn))
            # A global is worked out while the definitions are being
            # installed, so what it objects to is reported the way the
            # checks around it are rather than as a bare traceback.
            try:
                value = evaluator.eval_expr(defn.init_expr)
                unit = None
                if defn.unit_spec is not None:
                    from interp.units import eval_unit_formula
                    unit = eval_unit_formula(defn.unit_spec)
                if defn.type_annotation is None:
                    # A global is a binding like any other: without a
                    # type written down a number settles on int or
                    # float, and the bootstrap has neither.
                    check_binding_settles(value, defn.name)
                    check_bootstrap_binding(value, defn.name)
                    value = apply_unit(value, unit, evaluator._mk_int)
                elif isinstance(defn.init_expr, _ast.ArrayAlloc):
                    # An array declaration writes its shape in brackets
                    # that the annotation does not carry, and the
                    # allocation has already measured the value against
                    # the whole of it.  Coercing again here would meet
                    # the element type alone and take an array for it,
                    # which is what made a global fixed-size array
                    # impossible to write at all.
                    value = apply_unit(value, unit, evaluator._mk_int)
                else:
                    # The type says what each number is held in and the
                    # unit says what it counts, as at a local binding:
                    # for an array that means the elements.
                    value = coerce_to_type(value, defn.type_annotation, unit,
                                           evaluator._mk_int)
            except KeyError as e:
                raise DefinitionError(
                    f"in {defn.name}: {e.args[0] if e.args else e}",
                    _node_pos(defn)) from None
            except (OverflowError, TypeError, ValueError) as e:
                raise DefinitionError(
                    f"in {defn.name}: {strip_position_prefix(str(e))}",
                    extract_position(e) or _node_pos(defn)) from None
            env.unmark_global(defn.name)
            env.define(defn.name, value,
                        Decl(evaluator._declared_type_of(defn, value), unit))
            env.mark_global(defn.name, mutable=not defn.is_const)

    for defn in definitions:
        if isinstance(defn, ASTDestructureDef):
            if not redefine_vars:
                for name in _destructured_names(defn.names):
                    if name != DISCARD_NAME and name in env._frames[0]:
                        raise DefinitionError(
                            f"'{name}' is already defined; a file defines "
                            f"a name once (at the REPL a new let replaces "
                            f"the old)", _node_pos(defn))
            # A global may take a tuple apart as a local does; the
            # evaluator knows how, and what it binds becomes global.
            try:
                evaluator._eval_destructure(defn)
            except (OverflowError, TypeError, ValueError) as e:
                raise DefinitionError(
                    strip_position_prefix(str(e)),
                    extract_position(e) or _node_pos(defn)) from None
            for name in _destructured_names(defn.names):
                if name == DISCARD_NAME:
                    continue
                env.unmark_global(name)
                env.define(name, evaluator.env.lookup(name))
                env.mark_global(name, mutable=not defn.is_const)


    # Every struct exists by now, so a @repr(C) layout can be checked even
    # when it names a struct declared further down the file.  Checking here
    # rather than on first use means an unrepresentable field is reported
    # where it is written.
    for defn in definitions:
        if isinstance(defn, ASTStructDef) and defn.repr_kind is not None:
            try:
                struct_layout(env.lookup(defn.name), struct_lookup(env))
            except LayoutError as e:
                raise DefinitionError(str(e), _field_pos(defn, e.field))

    for defn in definitions:
        if isinstance(defn, ASTImplBlock):
            try:
                st = env.lookup(defn.struct_name)
            except KeyError:
                st = None
            if not isinstance(st, StructType):
                raise DefinitionError(
                    f"impl block for unknown struct '{defn.struct_name}'",
                    _node_pos(defn))
            for method_def in defn.methods:
                # A method's signature reads like any other, so the
                # redundant ∅ is worth the same word.
                program.warnings.extend(
                    _redundant_return_type_warning(method_def))
                for param_name, param_type in method_def.params:
                    # `self` names the receiver rather than stating what
                    # it takes, so it is the one parameter with nothing
                    # to say.
                    if param_type is None and param_name != "self":
                        raise DefinitionError(
                            _needs_a_type(f"{defn.struct_name}."
                                          f"{method_def.name}",
                                          _param_display(param_name)),
                            _param_pos(method_def, param_name))
                    if param_type is not None:
                        validate_param_type(param_type, method_def.name, param_name)
                if method_def.ret_type is not None and not validate_type(method_def.ret_type):
                    raise TypeError(
                        f"in {defn.struct_name}.{method_def.name}: "
                        f"unknown return type '{method_def.ret_type}'")
                fv = FuncValue(method_def.name, method_def.params,
                               method_def.body, env, method_def.ret_type,
                               is_impure=method_def.is_impure,
                               param_muts=method_def.param_muts,
                               ret_unit=method_def.ret_unit,
                               is_listable=method_def.is_listable,
                               is_noreturn=method_def.is_noreturn,
                               preconditions=method_def.preconditions,
                               postconditions=method_def.postconditions)
                if method_def.name in st.methods:
                    raise DefinitionError(
                        f"duplicate method '{method_def.name}' "
                        f"in impl {defn.struct_name}", _node_pos(method_def))
                try_err = _static_check_try(method_def, env)
                if try_err is not None:
                    raise DefinitionError(
                        f"in {defn.struct_name}.{method_def.name}: {try_err}",
                        _finding_pos(try_err) or _node_pos(method_def))
                match_err = _static_check_match(method_def, env)
                if match_err is not None:
                    raise DefinitionError(
                        f"in {defn.struct_name}.{method_def.name}: {match_err}",
                        _finding_pos(match_err) or _node_pos(method_def))
                st.methods[method_def.name] = fv
                if getattr(method_def, "_self_is_ref", False):
                    st._ref_self_methods.add(method_def.name)

    for defn in definitions:
        if isinstance(defn, ASTFuncDef) and not defn.expect_annotations:
            if not getattr(defn, "_parse_error", None):
                move_err = _static_check_moves(defn.body, env)
                if move_err is not None:
                    raise DefinitionError(f"in {defn.name}: {move_err}",
                                          _finding_pos(move_err) or _node_pos(defn))
                try_err = _static_check_try(defn, env)
                if try_err is not None:
                    raise DefinitionError(f"in {defn.name}: {try_err}",
                                          _finding_pos(try_err) or _node_pos(defn))
                match_err = _static_check_match(defn, env)
                if match_err is not None:
                    raise DefinitionError(f"in {defn.name}: {match_err}",
                                          _finding_pos(match_err) or _node_pos(defn))
                assert_err = _static_assert_check(defn, env)
                if assert_err is not None:
                    raise DefinitionError(f"in {defn.name}: {assert_err}",
                                          _finding_pos(assert_err) or _node_pos(defn))
                named_structs = _struct_vars_of(defn, env)
                return_err = (
                    _static_return_check(defn, named_structs)
                    or _static_lambda_return_check(defn, env, named_structs)
                    or _static_conditional_check(defn, named_structs))
                if return_err is not None:
                    raise DefinitionError(f"in {defn.name}: {return_err}",
                                          _finding_pos(return_err) or _node_pos(defn))
                noreturn_err = _static_noreturn_check(defn)
                if noreturn_err is not None:
                    raise DefinitionError(noreturn_err, _node_pos(defn))
                listable_err = _static_listable_check(defn)
                if listable_err is not None:
                    raise DefinitionError(listable_err, _node_pos(defn))
                loop_err = _static_loop_check(defn)
                if loop_err is not None:
                    raise DefinitionError(f"in {defn.name}: {loop_err}",
                                          _finding_pos(loop_err) or _node_pos(defn))
                literal_err = _static_literal_check(defn)
                if literal_err is not None:
                    raise DefinitionError(f"in {defn.name}: {literal_err}",
                                          _finding_pos(literal_err) or _node_pos(defn))
                chr_err = _static_chr_check(defn)
                if chr_err is not None:
                    raise DefinitionError(f"in {defn.name}: {chr_err}",
                                          _finding_pos(chr_err) or _node_pos(defn))
                semi_err = _trailing_semi_check(defn)
                if semi_err is not None:
                    raise DefinitionError(semi_err, _node_pos(defn))
                struct_vars = _struct_vars_of(defn, env)
                purity_err = _static_purity_check(defn, env, struct_vars)
                if purity_err is not None:
                    raise DefinitionError(f"in {defn.name}: {purity_err}",
                                          _finding_pos(purity_err) or _node_pos(defn))
                unused_err = _static_unused_value_check(defn, env, struct_vars)
                if unused_err is not None:
                    raise DefinitionError(f"in {defn.name}: {unused_err}",
                                          _finding_pos(unused_err) or _node_pos(defn))
                program.warnings.extend(
                    _redundant_return_type_warning(defn))
                program.warnings.extend(_unused_mut_warnings(defn))
                program.warnings.extend(_unused_loop_label_warnings(defn))
                program.warnings.extend(_unreachable_warnings(defn, env))
                program.warnings.extend(
                    _trailing_value_warnings(defn, env, struct_vars))

    # Every method is installed by now, so a call from one method to
    # another resolves whichever order the two were written in.
    for defn in definitions:
        if not isinstance(defn, ASTImplBlock):
            continue
        st = env.lookup(defn.struct_name)
        for method_def in defn.methods:
            struct_vars = _struct_vars_of(method_def, env, self_type=st)
            for finding in (_static_literal_check(method_def),
                            _static_chr_check(method_def),
                            _static_return_check(method_def, struct_vars),
                            _static_lambda_return_check(method_def, env,
                                                        struct_vars),
                            _static_conditional_check(method_def, struct_vars),
                            _static_purity_check(method_def, env, struct_vars),
                            _static_unused_value_check(method_def, env,
                                                       struct_vars)):
                if finding is not None:
                    raise DefinitionError(
                        f"in {defn.struct_name}.{method_def.name}: {finding}",
                        _finding_pos(finding) or _node_pos(method_def))
            program.warnings.extend(
                _trailing_value_warnings(method_def, env, struct_vars))


def _check_locale():
    """A locale that selects an encoding other than UTF-8 is fatal.

    The language's sources and I/O are UTF-8.  An environment whose
    locale demands another encoding cannot be honored, and honoring it
    halfway -- reading UTF-8 while the terminal expects Latin-1 --
    would corrupt quietly.  The C and POSIX locales and an unset one
    pass: they name no conflicting encoding.
    """
    value = (os.environ.get("LC_ALL") or os.environ.get("LC_CTYPE")
             or os.environ.get("LANG") or "")
    base = value.split("@")[0]
    if base in ("", "C", "POSIX"):
        return
    encoding = base.split(".", 1)[1] if "." in base else ""
    if encoding.lower().replace("-", "") != "utf8":
        print(f"fatal: the locale '{value}' does not select UTF-8; NGPL "
              f"sources and output are UTF-8, and a locale that says "
              f"otherwise cannot be honored", file=sys.stderr)
        sys.exit(1)


def main():
    """Run the NGPL interpreter on a source file."""
    # The evaluator spends several Python frames per NGPL call, so
    # Python's default limit caps an NGPL program at roughly 120 frames
    # of its own — too few for a recursive-descent parser over ordinary
    # nesting.  The limit is a backstop against runaway recursion, not a
    # resource budget, so it is raised rather than worked around.
    sys.setrecursionlimit(200_000)
    _check_locale()
    args = _parse_args()

    set_warnings_are_errors(args.werror)
    set_contract_semantic(args.contracts)

    # The forward-progress watchdog covers everything from here on --
    # loading, static checking, tests and the program itself -- so a
    # hang anywhere still ends in a diagnostic.
    timeout = args.timeout
    if timeout is None and os.environ.get("NGPLI_TIMEOUT"):
        timeout = float(os.environ["NGPLI_TIMEOUT"])
    heartbeat = args.heartbeat
    if heartbeat is None and os.environ.get("NGPLI_HEARTBEAT"):
        heartbeat = float(os.environ["NGPLI_HEARTBEAT"])
    if timeout is not None or heartbeat is not None:
        from interp.eval import arm_watchdog
        arm_watchdog(timeout, heartbeat)
    if args.fn_stats or os.environ.get("NGPLI_FN_STATS"):
        from interp.eval import enable_fn_stats
        enable_fn_stats()

    # Several sources are read as if they were one file: the program is
    # what they say together, in the order they were named.  The name of
    # the first stands for the whole where a single one is wanted -- as
    # the program's own argv[0] -- while `starts` remembers which line
    # each file began on, so a diagnostic still points into the file it
    # came from.
    source_paths = args.sources
    source_path = source_paths[0] if source_paths else None
    source = ""
    definitions = []

    if source_paths:
        pieces: list[str] = []
        starts: list[int] = []
        line_count = 0
        for path in source_paths:
            if not os.path.isfile(path):
                print(f"Error: file not found: {path}", file=sys.stderr)
                sys.exit(1)

            with open(path, "rb") as f:
                raw = f.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as e:
                # The language mandates UTF-8; what is not is refused
                # with its position rather than surfacing as a decoder
                # traceback.  The count is over this file's own bytes,
                # so it says the position in the file that is wrong.
                line = raw.count(b"\n", 0, e.start) + 1
                col = e.start - (raw.rfind(b"\n", 0, e.start) + 1) + 1
                print(f"error: {path}:{line}:{col}: the source is not "
                      f"UTF-8: byte 0x{raw[e.start]:02X} {e.reason}",
                      file=sys.stderr)
                sys.exit(1)

            # A file ends its last line before the next one starts.
            # Without this the two would run together into a single line
            # spanning a file boundary, which nothing downstream could
            # make sense of.
            if text and not text.endswith("\n"):
                text += "\n"
            starts.append(line_count + 1)
            line_count += text.count("\n")
            pieces.append(text)
        source = "".join(pieces)

        # A diagnostic raised mid-run never reaches the top level, so it
        # finds the text to point into here rather than being handed it.
        set_source(source, source_path, starts, source_paths)

        try:
            tokens = process_indentation(tokenize(source))
        except Exception as e:
            _show_error(e, source, source_path,
                        show_backtrace=args.interpreter_backtrace)
            sys.exit(1)

        try:
            parser = Parser(tokens)
            definitions = parser.parse()
        except Exception as e:
            _show_error(e, source, source_path,
                        show_backtrace=args.interpreter_backtrace)
            sys.exit(1)

        if not definitions and not args.repl:
            print("Warning: no definitions found in source file", file=sys.stderr)
            return
    elif args.test:
        print("Error: --test requires a source file", file=sys.stderr)
        sys.exit(1)

    env = Env()
    setup_std_env(env, source_path or "", args.program_args)

    evaluator = Evaluator(env)
    try:
        program = install_definitions(definitions, env, evaluator,
                                      honor_start=args.start is None)
    except DefinitionError as e:
        _report_warnings(e.warnings, source, source_path)
        if e.pos is not None:
            line, col, end_col = e.pos
            print(format_diagnostic(source, source_path, line, col, str(e),
                                    end_col=end_col),
                  file=sys.stderr)
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if program.build_func is not None:
        # The build function is read for what it declares -- search
        # paths and compiler flags land in std.build -- before anything
        # runs.  Running a build recipe belongs to the compiler.
        try:
            evaluator._call_user_func(program.build_func, [])
        except Exception as e:
            _show_error(e, source, source_path, evaluator,
                        show_backtrace=args.interpreter_backtrace)
            sys.exit(1)

    if _report_warnings(program.warnings, source, source_path) > 0 \
            and warnings_are_errors():
        # -Werror: what was reported are errors, and errors stop the run.
        sys.exit(1)

    startup_func = program.startup_func
    standalone_tests = program.standalone_tests
    referenced_tests = program.referenced_tests
    expect_funcs = program.expect_funcs

    if args.start is not None:
        try:
            val = env.lookup(args.start)
        except KeyError:
            val = None
        if not isinstance(val, FuncValue):
            print(f"Error: --start function '{args.start}' not found",
                  file=sys.stderr)
            sys.exit(1)
        if val.params:
            print(f"Error: --start function '{args.start}' must take "
                  f"no parameters", file=sys.stderr)
            sys.exit(1)
        startup_func = val

    # Process @expect-annotated functions: verify expected errors/warnings.
    expect_passed = 0
    expect_failed = 0
    for defn in expect_funcs:
        errors_produced: list[tuple[str, str]] = []

        parse_err = getattr(defn, "_parse_error", None)
        if parse_err is not None:
            errors_produced.append(("error", parse_err))

        if not parse_err:
            try:
                for param_name, param_type in defn.params:
                    if param_type is not None:
                        validate_param_type(param_type, defn.name,
                                            _param_display(param_name))
            except (TypeError, ValueError) as e:
                errors_produced.append(("error", str(e)))

        if not errors_produced:
            move_err = _static_check_moves(defn.body, env)
            if move_err is not None:
                errors_produced.append(("error", move_err))

        if not errors_produced:
            try_err = _static_check_try(defn, env)
            if try_err is not None:
                errors_produced.append(("error", try_err))

        if not errors_produced:
            match_err = _static_check_match(defn, env)
            if match_err is not None:
                errors_produced.append(("error", match_err))

        if not errors_produced:
            assert_err = _static_assert_check(defn, env)
            if assert_err is not None:
                errors_produced.append(("error", assert_err))

        if not errors_produced:
            named_structs = _struct_vars_of(defn, env)
            return_err = (
                _static_return_check(defn, named_structs)
                or _static_lambda_return_check(defn, env, named_structs)
                or _static_conditional_check(defn, named_structs))
            if return_err is not None:
                errors_produced.append(("error", return_err))

        if not errors_produced:
            noreturn_err = _static_noreturn_check(defn)
            if noreturn_err is not None:
                raise DefinitionError(noreturn_err, _node_pos(defn))
            listable_err = _static_listable_check(defn)
            if listable_err is not None:
                raise DefinitionError(listable_err, _node_pos(defn))
            loop_err = _static_loop_check(defn)
            if loop_err is not None:
                errors_produced.append(("error", loop_err))
            literal_err = _static_literal_check(defn)
            if literal_err is not None:
                errors_produced.append(("error", literal_err))

        if not errors_produced:
            chr_err = _static_chr_check(defn)
            if chr_err is not None:
                errors_produced.append(("error", chr_err))

        if not errors_produced:
            struct_vars = _struct_vars_of(defn, env)
            purity_err = _static_purity_check(defn, env, struct_vars)
            if purity_err is not None:
                errors_produced.append(("error", purity_err))

        if not errors_produced:
            unused_err = _static_unused_value_check(
                defn, env, _struct_vars_of(defn, env))
            if unused_err is not None:
                errors_produced.append(("error", unused_err))

        if not errors_produced:
            fv = FuncValue(defn.name, defn.params, defn.body, env, defn.ret_type,
                          defn.is_replaceable, defn.pack_param, defn.param_units,
                          defn.is_impure, param_refs=defn.param_refs,
                          param_muts=defn.param_muts, ret_unit=defn.ret_unit,
                          is_listable=defn.is_listable,
                          is_noreturn=defn.is_noreturn,
                          preconditions=defn.preconditions,
                          postconditions=defn.postconditions)
            eval_inst = Evaluator(env)
            # The body runs to be measured against its expectations, so
            # its warnings are collected for matching, not reported.
            eval_inst._collect_warnings = True
            try:
                eval_inst._call_user_func(fv, [])
            except Exception as e:
                errors_produced.append(("error", str(e)))
            errors_produced.extend(("warning", w) for w in eval_inst._warnings)

        # Added last: a non-empty list above skips running the function,
        # and the expected error would then never be produced.
        errors_produced.extend(
            ("warning", message)
            for message, _ in (_redundant_return_type_warning(defn)
                               + _unused_mut_warnings(defn)
                               + _unused_loop_label_warnings(defn)
                               + _unreachable_warnings(defn, env)
                               + _trailing_value_warnings(
                                   defn, env, _struct_vars_of(defn, env))))

        remaining = list(defn.expect_annotations)
        matched: list[tuple[str, str]] = []
        for level, msg in errors_produced:
            for i, (exp_level, exp_pattern) in enumerate(remaining):
                if (diagnostic_level(level) == diagnostic_level(exp_level)
                        and re.search(exp_pattern, msg)):
                    matched.append(remaining.pop(i))
                    break

        if remaining:
            expect_failed += 1
            unmatched_desc = "; ".join(
                f"@expect {lv} \"{pat}\"" for lv, pat in remaining)
            if errors_produced:
                got_desc = "; ".join(f"{lv}: {msg}" for lv, msg in errors_produced)
                print(f"test {defn.name} ... {_RED}{_BOLD}FAILED{_RESET}",
                      file=sys.stderr)
                print(f"  unmatched expectations: {unmatched_desc}", file=sys.stderr)
                print(f"  actual errors: {got_desc}", file=sys.stderr)
            else:
                print(f"test {defn.name} ... {_RED}{_BOLD}FAILED{_RESET}",
                      file=sys.stderr)
                print(f"  expected errors not produced: {unmatched_desc}",
                      file=sys.stderr)
        else:
            expect_passed += 1
            if args.test:
                print(f"test {defn.name} ... {_GREEN}ok{_RESET}", file=sys.stderr)

    if expect_failed > 0 and not args.test:
        sys.exit(1)

    if args.test:
        all_tests: list[FuncValue] = list(standalone_tests)
        seen: set[str] = {t.name for t in all_tests}
        for tests in referenced_tests.values():
            for t in tests:
                if t.name not in seen:
                    seen.add(t.name)
                    all_tests.append(t)

        total_tests = len(all_tests) + expect_passed + expect_failed
        if total_tests == 0:
            # A file with nothing to run must not read as a file whose
            # tests all passed; that is how 83 tests once went unrun.
            print("error: no tests: nothing in this file is marked "
                  "@test or @expect", file=sys.stderr)
            sys.exit(1)
        print(f"\nrunning {total_tests} tests", file=sys.stderr)
        passed = expect_passed
        failed = expect_failed
        for test_fv in all_tests:
            ok, msg = _run_test(test_fv, env, source, source_path)
            if ok:
                print(f"test {test_fv.name} ... {_GREEN}ok{_RESET}", file=sys.stderr)
                passed += 1
            else:
                print(f"test {test_fv.name} ... {_RED}{_BOLD}FAILED{_RESET}", file=sys.stderr)
                print(msg, file=sys.stderr)
                failed += 1

        if failed == 0:
            status = f"{_GREEN}ok{_RESET}"
        else:
            status = f"{_RED}{_BOLD}FAILED{_RESET}"
        print(f"\ntest result: {status}. {passed} passed; {failed} failed", file=sys.stderr)
        sys.exit(0 if failed == 0 else 1)

    # Normal mode: run standalone tests before startup unless skipped.
    # Only report failures; abort if any test failed.
    if not args.skip_tests:
        any_failed = False
        for test_fv in standalone_tests:
            ok, msg = _run_test(test_fv, env, source, source_path)
            if not ok:
                print(f"test {test_fv.name} ... {_RED}{_BOLD}FAILED{_RESET}",
                      file=sys.stderr)
                print(msg, file=sys.stderr)
                any_failed = True
        if any_failed:
            sys.exit(1)

    # Without a startup function there is nothing to run, so hand the
    # session to the user rather than exiting silently.
    if args.repl or startup_func is None:
        from interp.repl import Repl
        hooks = {} if args.skip_tests else dict(referenced_tests)
        sys.exit(Repl(env, Evaluator(env, test_hooks=hooks)).run())

    hooks = {} if args.skip_tests else dict(referenced_tests)
    evaluator = Evaluator(env, test_hooks=hooks)
    try:
        result = evaluator._call_user_func(startup_func, [])
    except ProgramExit as e:
        # A deliberate exit, so no diagnostic and no backtrace.
        sys.exit(e.code)
    except ProgramAbort as e:
        _report_abort(e, source_path, args.interpreter_backtrace)
    except AssertionError as e:
        _show_error(e, source, source_path, evaluator,
                    show_backtrace=args.interpreter_backtrace)
        sys.exit(1)
    except Exception as e:
        _show_error(e, source, source_path, evaluator,
                    show_backtrace=args.interpreter_backtrace)
        sys.exit(1)

    exit_code = _start_exit_code(result, startup_func, source, source_path)
    sys.exit(exit_code)


def _start_exit_code(result: object, func: FuncValue,
                     source: str, source_path: str) -> int:
    """Derive a process exit code from the @start function's return value."""
    ret = func.ret_type
    if ret is None or ret == "\N{EMPTY SET}":
        return 0
    if ret in ("u8", "i8"):
        val = unwrap_optional(result)
        if isinstance(val, IntValue):
            if ret == "i8":
                v = val.value
                if v < -128 or v > 127:
                    v = v & 0xff
                    if v >= 128:
                        v -= 256
                return v & 0xff
            return val.value & 0xff
        return 0
    # Under -Werror the signature is refused rather than worked around,
    # so the status says the run did not go through.
    level = diagnostic_level("warning")
    print(f"{level}: @start function '{func.name}' has return type "
          f"'{ret}' which is not u8, i8, or \N{EMPTY SET}"
          + ("" if level == "error" else "; using exit code 0"),
          file=sys.stderr)
    return 1 if level == "error" else 0


if __name__ == "__main__":
    main()
