"""Entry point for the newlang prototype interpreter.

Usage:
    python3 main.py <source_file.nl>

The interpreter:
    1. Reads the source file.
    2. Tokenizes it (lexer).
    3. Parses it into an AST (parser).
    4. Sets up the initial environment with std module bindings.
    5. Locates and executes the @start-marked function, or all functions if none marked.

All source files are UTF-8 encoded.
"""

import sys
import os

from interp.lexer import tokenize
from interp.parser import Parser
from interp.env import Env
from interp.ast import FuncDef as ASTFuncDef
from interp.value import (
    FuncValue, BuiltinFunc, ObjectValue, IntValue, StrValue, BoolValue, ArrayValue,
)
from interp.eval import Evaluator


def setup_std_env(env: Env):
    """Register the std module in the given environment.

    Only a single `std` name is defined; all runtime services are accessed
    through it (e.g. ``std.fs.cwd()``, ``std.sha256(data)``).
    """
    from interp.std import std
    env.define("std", ObjectValue(std))


def main():
    """Run the newlang interpreter on a source file."""
    if len(sys.argv) < 2:
        print("Usage: python3 main.py <source_file.nl>", file=sys.stderr)
        sys.exit(1)

    source_path = sys.argv[1]
    if not os.path.isfile(source_path):
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    # Read source.
    with open(source_path, "r", encoding="utf-8") as f:
        source = f.read()

    # Tokenize.
    tokens = tokenize(source)

    # Parse.
    parser = Parser(tokens)
    definitions = parser.parse()

    if not definitions:
        print("Warning: no definitions found in source file", file=sys.stderr)
        return

    # Set up environment with std builtins.
    env = Env()
    setup_std_env(env)

    # Evaluate and register top-level const definitions (static arrays).
    evaluator = Evaluator(env)
    for defn in definitions:
        if isinstance(defn, tuple) and len(defn) == 3 and defn[0] == "const_assign":
            _, name, init_expr = defn
            arr_value = evaluator.eval_expr(init_expr)
            env.define(name, arr_value)

    # Register all function definitions in the global environment.
    for defn in definitions:
        if isinstance(defn, FuncValue):
            env.define(defn.name, defn)
        elif isinstance(defn, ASTFuncDef):
            # Convert AST-level FuncDef to runtime FuncValue.
            fv = FuncValue(defn.name, defn.params, defn.body, env, defn.ret_type)
            env.define(defn.name, fv)
        elif not isinstance(defn, tuple):
            # VarDef or other non-tuple definition — register by name.
            env.define(defn.name, defn)

    # Find and execute the startup function.
    startup_func = None
    for defn in definitions:
        if getattr(defn, "is_start", False):
            if startup_func is not None:
                print("Error: multiple @start functions defined", file=sys.stderr)
                sys.exit(1)
            startup_func = defn

    if startup_func is None:
        print("No @start function found — nothing to execute", file=sys.stderr)
        return

    # Evaluate the startup function body.
    try:
        eval_result = Evaluator(env).eval_stmts(startup_func.body)
    except Exception as e:
        print(f"Runtime error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
