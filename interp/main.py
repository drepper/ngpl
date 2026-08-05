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

import sys
import os
from collections import defaultdict

from interp.lexer import tokenize, process_indentation
from interp.parser import Parser
from interp.env import Env
from interp.ast import FuncDef as ASTFuncDef
from interp.value import (
    FuncValue, BuiltinFunc, ObjectValue, IntValue, StrValue, BoolValue, ArrayValue,
    NoneValue, coerce_to_type, validate_param_type, none,
)
from interp.eval import Evaluator, unwrap_optional


def setup_std_env(env: Env):
    """Register the std module and assertion builtins in the given environment."""
    from interp.std import std
    env.define("std", ObjectValue(std))
    env.define("assert", BuiltinFunc("assert", -1, _builtin_assert))
    env.define("assert_eq", BuiltinFunc("assert_eq", 2, _builtin_assert_eq))


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
    expected = unwrap_optional(args[0])
    actual = unwrap_optional(args[1])
    if isinstance(expected, IntValue) and isinstance(actual, IntValue):
        if expected.value != actual.value:
            raise AssertionError(
                f"assert_eq failed:\n  expected: {_format_value(expected)}\n  actual:   {_format_value(actual)}")
    elif expected.to_python() != actual.to_python():
        raise AssertionError(
            f"assert_eq failed:\n  expected: {_format_value(expected)}\n  actual:   {_format_value(actual)}")
    return none()


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
            value = evaluator.eval_expr(init_expr)
            if type_ann is not None:
                value = coerce_to_type(value, type_ann)
            env.define(name, value)

    startup_func: FuncValue | None = None
    standalone_tests: list[FuncValue] = []
    referenced_tests: dict[str, list[FuncValue]] = defaultdict(list)

    for defn in definitions:
        if isinstance(defn, ASTFuncDef):
            for param_name, param_type in defn.params:
                if param_type is not None:
                    validate_param_type(param_type, defn.name, param_name)
            fv = FuncValue(defn.name, defn.params, defn.body, env, defn.ret_type)
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

    if test_mode:
        all_tests: list[FuncValue] = list(standalone_tests)
        seen: set[str] = {t.name for t in all_tests}
        for tests in referenced_tests.values():
            for t in tests:
                if t.name not in seen:
                    seen.add(t.name)
                    all_tests.append(t)

        print(f"\nrunning {len(all_tests)} tests", file=sys.stderr)
        passed = 0
        failed = 0
        for test_fv in all_tests:
            ok, msg = _run_test(test_fv, env)
            if ok:
                print(f"test {test_fv.name} ... ok", file=sys.stderr)
                passed += 1
            else:
                print(f"test {test_fv.name} ... FAILED", file=sys.stderr)
                print(f"  {msg}", file=sys.stderr)
                failed += 1

        status = "ok" if failed == 0 else "FAILED"
        print(f"\ntest result: {status}. {passed} passed; {failed} failed", file=sys.stderr)
        sys.exit(0 if failed == 0 else 1)

    # Normal mode: run standalone tests before startup unless skipped.
    if not skip_tests:
        for test_fv in standalone_tests:
            ok, msg = _run_test(test_fv, env)
            if ok:
                print(f"test {test_fv.name} ... ok", file=sys.stderr)
            else:
                print(f"test {test_fv.name} ... FAILED: {msg}", file=sys.stderr)
                sys.exit(1)

    if startup_func is None:
        print("No @start function found — nothing to execute", file=sys.stderr)
        return

    hooks = {} if skip_tests else dict(referenced_tests)
    try:
        Evaluator(env, test_hooks=hooks).eval_stmts(startup_func.body)
    except AssertionError as e:
        print(f"Test failure: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Runtime error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
