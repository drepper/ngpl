"""Entry point for the NGPL prototype interpreter."""

import argparse
import re
import signal
import sys
import os
from collections import defaultdict

from interp.lexer import tokenize, process_indentation
from interp.parser import Parser
from interp.env import Env
from interp.ast import (
    FuncDef as ASTFuncDef, EnumDef as ASTEnumDef, UnitDef as ASTUnitDef,
    VarDef as ASTVarDef, TypeDef as ASTTypeDef,
    StructDef as ASTStructDef, ImplBlock as ASTImplBlock,
)
import interp.ast as _ast
from interp.value import (
    FuncValue, BuiltinFunc, ObjectValue, IntValue, StrValue, BoolValue, ArrayValue,
    NoneValue, SomeValue, ExpectedValue, EnumType, EnumValue, StructType,
    coerce_to_type, validate_param_type, validate_type, none, FAST_TYPES,
    register_type_alias, register_sum_type, register_enum_type,
    sum_type_alternatives, register_user_type, DISCARD_NAME,
    _split_optional_type,
)
from interp.eval import Evaluator, unwrap_optional, _ARRAY_MUTATORS
from interp.layout import LayoutError, struct_layout, struct_lookup
from interp.errors import (format_diagnostic, extract_position,
                           strip_position_prefix, format_backtrace,
                           ProgramExit, ProgramAbort)


def _make_std_errors() -> EnumType:
    """Create the std.errors enum with error codes grouped by category."""
    members = {
        # Runtime errors (100-199)
        "division_by_zero": 100,
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
        prog="NGPL",
        description="Prototype interpreter for the NGPL programming language.",
    )
    parser.add_argument("source", nargs="?",
                        help="source file to interpret; without one the "
                             "interpreter starts a REPL")
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
    parser.add_argument("--interpreter-backtrace", action="store_true",
                       help="show the Python interpreter backtrace on errors")
    parser.add_argument("program_args", nargs=argparse.REMAINDER,
                       help="arguments passed to the interpreted program; "
                            "separate them from the interpreter's own options "
                            "with --")
    return parser.parse_args()


def _program_args(raw: list[str]) -> list[str]:
    """Strip the optional `--` separator from the interpreted program's args.

    argparse.REMAINDER keeps the separator when one is present, but the
    program should see only what follows it.
    """
    if raw and raw[0] == "--":
        return raw[1:]
    return raw


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


def _iter_ast(node, stop_at=()):
    """Yield every AST node reachable from node, itself included.

    Nodes listed in stop_at are yielded but not descended into, so a
    caller can treat them as boundaries and handle their contents on
    their own terms.
    """
    if isinstance(node, (list, tuple)):
        for item in node:
            yield from _iter_ast(item, stop_at)
        return
    if type(node).__module__ != "interp.ast":
        return
    yield node
    if stop_at and isinstance(node, stop_at):
        return
    for value in vars(node).values():
        yield from _iter_ast(value, stop_at)


def _propagated_error_type(expr, env) -> str | None:
    """The error type an expression can produce, when it is knowable.

    Returns None when the expression's error type cannot be determined
    without evaluating it, in which case no static claim is made.
    """
    if isinstance(expr, _ast.BinOp) and expr.op in ("/", "%"):
        # Division and remainder report failure as std.errors.
        return "std.errors"
    if isinstance(expr, _ast.FuncCall):
        try:
            callee = env.lookup(expr.name)
        except KeyError:
            return None
        ret_type = getattr(callee, "ret_type", None)
        if not ret_type:
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
            return (f"? requires the {where} to return an optional or an "
                    f"expected type, but it returns "
                    f"'{ret_type or chr(8709)}'")
        if opt_err == "":
            continue
        source = _propagated_error_type(node.expr, env)
        if source is not None and source != opt_err:
            return (f"? propagates an error of type '{source}', but the "
                    f"{where} returns errors of type '{opt_err}'")
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
_SUBJECT_NAME = {"optional": "an optional", "expected": "a result",
                 "plain": "a plain value"}


def _declared_sum_type(name: str, func_def) -> str | None:
    """The sum type a parameter of this function was declared with.

    A parameter is where a type is written down.  A name bound from an
    expression carries the alternative's own type instead, and nothing
    is claimed about it here.
    """
    for param in func_def.params:
        param_name = param[0] if isinstance(param, tuple) else param
        param_type = param[1] if isinstance(param, tuple) else None
        if param_name != name or param_type is None:
            continue
        if sum_type_alternatives(param_type) is not None:
            return param_type
    return None


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
    # A name declared with a sum type is matched by alternative, and
    # the type is what says which alternatives there are.
    if isinstance(expr, _ast.VarRef) and func_def is not None:
        declared = _declared_sum_type(expr.name, func_def)
        if declared is not None:
            return declared

    if isinstance(expr, (_ast.OptSome, _ast.NoneLit)):
        return "optional"
    if isinstance(expr, _ast.ExpErr):
        return "expected"
    if isinstance(expr, _ast.BinOp) and expr.op in ("/", "%"):
        return "expected"
    if isinstance(expr, _ast.FuncCall):
        try:
            callee = env.lookup(expr.name)
        except KeyError:
            return None
        ret_type = getattr(callee, "ret_type", None)
        if not ret_type:
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
            return (f"match repeats the {_arm_pattern(arm)} pattern; "
                    f"the second one can never be reached")
        seen.add(key)
        if arm.kind == "wildcard" and index != len(node.arms) - 1:
            return "match has arms after _, which can never be reached"

    subject = _match_subject_kind(node.subject, env, func_def)
    if subject is None:
        return None

    alternatives = sum_type_alternatives(subject)
    if alternatives is not None:
        for arm in node.arms:
            if arm.kind == "wildcard":
                continue
            if arm.kind != "type":
                return (f"{_arm_pattern(arm)} cannot match '{subject}', "
                        f"which is {' | '.join(alternatives)}")
            if arm.type_name not in alternatives:
                return (f"'{arm.type_name}' is not an alternative of "
                        f"'{subject}', which is "
                        f"{' | '.join(alternatives)}")
        if "wildcard" in seen:
            return None
        missing = [a for a in alternatives if a not in seen]
        if missing:
            return ("match has no arm for "
                    + " or ".join(missing)
                    + "; add the missing pattern or a _ arm")
        return None

    shapes = _SUBJECT_SHAPES[subject]

    for arm in node.arms:
        if arm.kind == "wildcard" or arm.kind in shapes:
            continue
        hint = {"none": ", whose failure is \N{THERE DOES NOT EXIST}(e)",
                "err": ", whose absence is \N{EMPTY SET}"}.get(arm.kind, "")
        return (f"{_arm_pattern(arm)} cannot match "
                f"{_SUBJECT_NAME[subject]}{hint}")

    if "wildcard" in seen:
        return None
    missing = sorted(shapes - seen)
    if missing:
        return ("match has no arm for "
                + " or ".join(_ARM_SUBJECT[m] for m in missing)
                + "; add the missing pattern or a _ arm")
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
        for value in vars(node).values():
            yield from walk(value)

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
        # x.push(...) and the other methods that change an array
        if isinstance(node, _ast.MethodCall):
            if node.method in _ARRAY_MUTATORS:
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
                    return f"use of moved value '{name}'"

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
                    return f"use of moved value '{name}'"
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
    """A top-level definition could not be installed into the environment."""


class LoadedProgram:
    """The parts of a program that installing its definitions produced."""

    def __init__(self):
        self.startup_func: FuncValue | None = None
        self.standalone_tests: list[FuncValue] = []
        self.referenced_tests: dict[str, list[FuncValue]] = defaultdict(list)
        self.expect_funcs: list[ASTFuncDef] = []
        # (message, position) pairs found while installing definitions.
        self.warnings: list[tuple[str, tuple | None]] = []


def install_definitions(definitions, env: Env, evaluator: Evaluator, *,
                        honor_start: bool = True) -> LoadedProgram:
    """Install top-level definitions into an environment.

    Definitions are installed in dependency order: type aliases, then
    variables, units, enums, structs, functions, and finally impl blocks,
    which need their struct to exist already.

    Args:
        definitions: the parsed top-level definitions.
        env: the environment to define names in.
        evaluator: used to evaluate variable initializers.
        honor_start: whether an @start annotation designates the startup
            function.  False when the command line already named one.

    Returns:
        A LoadedProgram holding the startup function and the tests found.

    Raises:
        DefinitionError: when a definition is not well-formed.
    """
    program = LoadedProgram()

    # Named types first: an alias, a sum, a global, or a signature
    # may refer to any of them, and each may be declared below
    # whatever names it.

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
            et = EnumType(defn.name, defn.underlying_type, members, defn.is_flag)
            register_enum_type(defn.name, defn.underlying_type)
            env.define(defn.name, et)

    for defn in definitions:
        if isinstance(defn, ASTStructDef):
            register_user_type(defn.name)
            st = StructType(defn.name, defn.fields, repr_kind=defn.repr_kind)
            env.define(defn.name, st)

    # Every struct and enum exists by now, so an alternative may be
    # declared below the sum type that names it.
    for defn in definitions:
        if isinstance(defn, _ast.SumTypeDef):
            for alt in defn.alternatives:
                if not validate_type(alt):
                    raise DefinitionError(
                        f"sum type '{defn.name}' names unknown type "
                        f"'{alt}' as an alternative")
            register_sum_type(defn.name, defn.alternatives)

    for defn in definitions:
        if isinstance(defn, ASTTypeDef):
            if not validate_type(defn.target):
                raise DefinitionError(
                    f"type alias '{defn.name}' refers to unknown type "
                    f"'{defn.target}'")
            register_type_alias(defn.name, defn.target)

    for defn in definitions:
        if isinstance(defn, ASTVarDef):
            if defn.name == DISCARD_NAME:
                # Evaluated for its effects, then dropped; nothing is bound.
                evaluator.eval_expr(defn.init_expr)
                continue
            if defn.is_const and defn.type_annotation is not None and defn.type_annotation in FAST_TYPES:
                raise DefinitionError(
                    f"fast type '{defn.type_annotation}' cannot be used in "
                    f"let definition '{defn.name}'")
            value = evaluator.eval_expr(defn.init_expr)
            if defn.type_annotation is not None:
                value = coerce_to_type(value, defn.type_annotation)
            env.define(defn.name, value)
            if defn.is_const:
                env._const_globals.add(defn.name)
            else:
                env._mutable_globals.add(defn.name)

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

    # Every struct exists by now, so a @repr(C) layout can be checked even
    # when it names a struct declared further down the file.  Checking here
    # rather than on first use means an unrepresentable field is reported
    # where it is written.
    for defn in definitions:
        if isinstance(defn, ASTStructDef) and defn.repr_kind is not None:
            try:
                struct_layout(env.lookup(defn.name), struct_lookup(env))
            except LayoutError as e:
                raise DefinitionError(str(e))

    for defn in definitions:
        if isinstance(defn, ASTFuncDef):
            if defn.expect_annotations:
                program.expect_funcs.append(defn)
                continue

            for param_name, param_type in defn.params:
                if param_type is not None:
                    validate_param_type(param_type, defn.name, param_name)
            if defn.pack_param is not None:
                pp_name, pp_type = defn.pack_param
                if pp_type is not None:
                    validate_param_type(pp_type, defn.name, pp_name)
            if defn.ret_type is not None and not validate_type(defn.ret_type):
                raise TypeError(
                    f"in {defn.name}: unknown return type '{defn.ret_type}'")
            fv = FuncValue(defn.name, defn.params, defn.body, env, defn.ret_type,
                          defn.is_replaceable, defn.pack_param, defn.param_units,
                          defn.is_impure, param_refs=defn.param_refs,
                          param_muts=defn.param_muts)
            env.define(defn.name, fv)

            if honor_start and defn.is_start:
                if program.startup_func is not None:
                    raise DefinitionError("multiple @start functions defined")
                program.startup_func = fv

            if defn.is_test:
                if defn.test_refs:
                    for ref in defn.test_refs:
                        program.referenced_tests[ref].append(fv)
                else:
                    program.standalone_tests.append(fv)

    for defn in definitions:
        if isinstance(defn, ASTImplBlock):
            try:
                st = env.lookup(defn.struct_name)
            except KeyError:
                st = None
            if not isinstance(st, StructType):
                raise DefinitionError(
                    f"impl block for unknown struct '{defn.struct_name}'")
            for method_def in defn.methods:
                for param_name, param_type in method_def.params:
                    if param_type is not None:
                        validate_param_type(param_type, method_def.name, param_name)
                if method_def.ret_type is not None and not validate_type(method_def.ret_type):
                    raise TypeError(
                        f"in {defn.struct_name}.{method_def.name}: "
                        f"unknown return type '{method_def.ret_type}'")
                fv = FuncValue(method_def.name, method_def.params,
                               method_def.body, env, method_def.ret_type,
                               is_impure=method_def.is_impure,
                               param_muts=method_def.param_muts)
                if method_def.name in st.methods:
                    raise DefinitionError(
                        f"duplicate method '{method_def.name}' "
                        f"in impl {defn.struct_name}")
                try_err = _static_check_try(method_def, env)
                if try_err is not None:
                    raise DefinitionError(
                        f"in {defn.struct_name}.{method_def.name}: {try_err}")
                match_err = _static_check_match(method_def, env)
                if match_err is not None:
                    raise DefinitionError(
                        f"in {defn.struct_name}.{method_def.name}: {match_err}")
                st.methods[method_def.name] = fv
                if getattr(method_def, "_self_is_ref", False):
                    st._ref_self_methods.add(method_def.name)

    for defn in definitions:
        if isinstance(defn, ASTFuncDef) and not defn.expect_annotations:
            if not getattr(defn, "_parse_error", None):
                move_err = _static_check_moves(defn.body, env)
                if move_err is not None:
                    raise DefinitionError(f"in {defn.name}: {move_err}")
                try_err = _static_check_try(defn, env)
                if try_err is not None:
                    raise DefinitionError(f"in {defn.name}: {try_err}")
                match_err = _static_check_match(defn, env)
                if match_err is not None:
                    raise DefinitionError(f"in {defn.name}: {match_err}")
                program.warnings.extend(_unused_mut_warnings(defn))

    return program


def main():
    """Run the NGPL interpreter on a source file."""
    args = _parse_args()

    source_path = args.source
    source = ""
    definitions = []

    if source_path is not None:
        if not os.path.isfile(source_path):
            print(f"Error: file not found: {source_path}", file=sys.stderr)
            sys.exit(1)

        with open(source_path, "r", encoding="utf-8") as f:
            source = f.read()

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
    setup_std_env(env, source_path or "", _program_args(args.program_args))

    evaluator = Evaluator(env)
    try:
        program = install_definitions(definitions, env, evaluator,
                                      honor_start=args.start is None)
    except DefinitionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    for message, position in program.warnings:
        if position is not None:
            line, col, end_col = position
            print(format_diagnostic(source, source_path, line, col, message,
                                    end_col=end_col, level="warning"),
                  file=sys.stderr)
        else:
            print(f"warning: {message}", file=sys.stderr)

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
                        validate_param_type(param_type, defn.name, param_name)
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
            fv = FuncValue(defn.name, defn.params, defn.body, env, defn.ret_type,
                          defn.is_replaceable, defn.pack_param, defn.param_units,
                          defn.is_impure, param_refs=defn.param_refs,
                          param_muts=defn.param_muts)
            eval_inst = Evaluator(env)
            try:
                eval_inst._call_user_func(fv, [])
            except Exception as e:
                errors_produced.append(("error", str(e)))
            errors_produced.extend(("warning", w) for w in eval_inst._warnings)

        # Added last: a non-empty list above skips running the function,
        # and the expected error would then never be produced.
        errors_produced.extend(
            ("warning", message)
            for message, _ in _unused_mut_warnings(defn))

        remaining = list(defn.expect_annotations)
        matched: list[tuple[str, str]] = []
        for level, msg in errors_produced:
            for i, (exp_level, exp_pattern) in enumerate(remaining):
                if level == exp_level and re.search(exp_pattern, msg):
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
    print(f"warning: @start function '{func.name}' has return type "
          f"'{ret}' which is not u8, i8, or \N{EMPTY SET}; "
          f"using exit code 0",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    main()
