"""Entry point for the newlang prototype interpreter.

Usage:
    python3 -m interp.main <source_file.nl> [--test] [--skip-tests]

The interpreter:
    1. Reads the source file.
    2. Tokenizes it (lexer).
    3. Parses it into an AST (parser).
    4. Sets up the initial environment with std module bindings.
    5. Runs tests (standalone before startup, referenced on first call).
    6. Locates and executes the @start-marked function.

Flags:
    --test        Run all tests and exit without executing the startup function.
    --skip-tests  Skip all tests during normal execution.

All source files are UTF-8 encoded.
"""

import re
import sys
import os
from collections import defaultdict

from interp.lexer import tokenize, process_indentation
from interp.parser import Parser
from interp.env import Env
from interp.ast import FuncDef as ASTFuncDef, EnumDef as ASTEnumDef
from interp.value import (
    FuncValue, BuiltinFunc, ObjectValue, IntValue, StrValue, BoolValue, ArrayValue,
    NoneValue, ExpectedValue, EnumType, EnumValue,
    coerce_to_type, validate_param_type, validate_type, none, FAST_TYPES,
)
from interp.eval import Evaluator, unwrap_optional


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


def setup_std_env(env: Env):
    """Register the std module and assertion builtins in the given environment."""
    from interp.std import std
    std.errors = _make_std_errors()
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
    return v.display()


def _builtin_assert_eq(args):
    """assert_eq(expected, actual) -- fail if values differ."""
    if len(args) != 2:
        raise TypeError("assert_eq requires exactly 2 arguments")
    a0, a1 = args[0], args[1]
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


def _run_test(test_fv: FuncValue, env: Env) -> tuple[bool, str]:
    """Run a single test function, return (passed, error_message)."""
    try:
        Evaluator(env)._call_user_func(test_fv, [])
        return True, ""
    except AssertionError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


def main():
    """Run the newlang interpreter on a source file."""
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    test_mode = "--test" in sys.argv
    skip_tests = "--skip-tests" in sys.argv

    if len(args) < 1:
        print("Usage: python3 -m interp.main <source_file.nl> [--test] [--skip-tests]", file=sys.stderr)
        sys.exit(1)

    source_path = args[0]
    if not os.path.isfile(source_path):
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    with open(source_path, "r", encoding="utf-8") as f:
        source = f.read()

    tokens = process_indentation(tokenize(source))
    parser = Parser(tokens)
    definitions = parser.parse()

    if not definitions:
        print("Warning: no definitions found in source file", file=sys.stderr)
        return

    env = Env()
    setup_std_env(env)

    evaluator = Evaluator(env)
    for defn in definitions:
        if isinstance(defn, tuple) and len(defn) == 4 and defn[0] == "const_assign":
            _, name, type_ann, init_expr = defn
            if type_ann is not None and type_ann in FAST_TYPES:
                print(f"Error: fast type '{type_ann}' cannot be used in const definition '{name}'",
                      file=sys.stderr)
                sys.exit(1)
            value = evaluator.eval_expr(init_expr)
            if type_ann is not None:
                value = coerce_to_type(value, type_ann)
            env.define(name, value)

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
            env.define(defn.name, et)

    startup_func: FuncValue | None = None
    standalone_tests: list[FuncValue] = []
    referenced_tests: dict[str, list[FuncValue]] = defaultdict(list)
    expect_funcs: list[ASTFuncDef] = []

    for defn in definitions:
        if isinstance(defn, ASTFuncDef):
            if defn.expect_annotations:
                expect_funcs.append(defn)
                continue

            for param_name, param_type in defn.params:
                if param_type is not None:
                    validate_param_type(param_type, defn.name, param_name)
            if defn.ret_type is not None and not validate_type(defn.ret_type):
                raise TypeError(
                    f"in {defn.name}: unknown return type '{defn.ret_type}'")
            fv = FuncValue(defn.name, defn.params, defn.body, env, defn.ret_type,
                          defn.is_replaceable)
            env.define(defn.name, fv)

            if defn.is_start:
                if startup_func is not None:
                    print("Error: multiple @start functions defined", file=sys.stderr)
                    sys.exit(1)
                startup_func = fv

            if defn.is_test:
                if defn.test_refs:
                    for ref in defn.test_refs:
                        referenced_tests[ref].append(fv)
                else:
                    standalone_tests.append(fv)

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
            fv = FuncValue(defn.name, defn.params, defn.body, env, defn.ret_type,
                          defn.is_replaceable)
            eval_inst = Evaluator(env)
            try:
                eval_inst._call_user_func(fv, [])
            except Exception as e:
                errors_produced.append(("error", str(e)))
            errors_produced.extend(("warning", w) for w in eval_inst._warnings)

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
            if test_mode:
                print(f"test {defn.name} ... {_GREEN}ok{_RESET}", file=sys.stderr)

    if expect_failed > 0 and not test_mode:
        sys.exit(1)

    if test_mode:
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
            ok, msg = _run_test(test_fv, env)
            if ok:
                print(f"test {test_fv.name} ... {_GREEN}ok{_RESET}", file=sys.stderr)
                passed += 1
            else:
                print(f"test {test_fv.name} ... {_RED}{_BOLD}FAILED{_RESET}", file=sys.stderr)
                print(f"  {msg}", file=sys.stderr)
                failed += 1

        if failed == 0:
            status = f"{_GREEN}ok{_RESET}"
        else:
            status = f"{_RED}{_BOLD}FAILED{_RESET}"
        print(f"\ntest result: {status}. {passed} passed; {failed} failed", file=sys.stderr)
        sys.exit(0 if failed == 0 else 1)

    # Normal mode: run standalone tests before startup unless skipped.
    # Only report failures; abort if any test failed.
    if not skip_tests:
        any_failed = False
        for test_fv in standalone_tests:
            ok, msg = _run_test(test_fv, env)
            if not ok:
                print(f"test {test_fv.name} ... {_RED}{_BOLD}FAILED{_RESET}: {msg}", file=sys.stderr)
                any_failed = True
        if any_failed:
            sys.exit(1)

    if startup_func is None:
        print("No @start function found — nothing to execute", file=sys.stderr)
        return

    hooks = {} if skip_tests else dict(referenced_tests)
    try:
        Evaluator(env, test_hooks=hooks).eval_stmts(startup_func.body)
    except AssertionError as e:
        print(f"{_RED}{_BOLD}Test failure{_RESET}: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Runtime error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
