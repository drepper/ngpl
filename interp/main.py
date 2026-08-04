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
from interp.value import (
    FuncValue, BuiltinFunc, ObjectValue, IntValue, StrValue, BoolValue,
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

    # Register all function definitions in the global environment.
    for defn in definitions:
        if isinstance(defn, FuncValue):
            env.define(defn.name, defn)
        elif hasattr(defn, "name"):  # FuncDef from AST
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
