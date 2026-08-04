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
    """Register std module builtins in the given environment.

    Adds fs.cwd(), heap.alloc(), sha256(), format(), get_stdout()
    as builtin functions to the global scope.
    """
    from interp.std import std, _sha256

    # fs.cwd → BuiltinFunc
    def _fs_cwd_wrapper(args):
        if len(args) != 0:
            raise TypeError("fs.cwd() takes no arguments")
        return ObjectValue(std.fs.cwd())
    env.define("fs", ObjectValue(std.fs))

    # heap.allocator → call std.get_allocator()
    class _HeapModule:
        """The heap submodule — provides allocator access."""
        def __init__(self, std_ref):
            self._std = std_ref
        def allocator(self):
            return self._std.get_allocator()

    env.define("heap", ObjectValue(_HeapModule(std)))

    # sha256(data) → IntValue
    def _sha256_wrapper(args):
        if len(args) != 1:
            raise TypeError("sha256() takes 1 argument")
        data_arg = args[0]
        # Unwrap optional if needed.
        from interp.eval import unwrap_optional
        data_val = unwrap_optional(data_arg)
        if isinstance(data_val, ObjectValue):
            obj = data_val.obj
            if hasattr(obj, "data"):  # Bytes object
                data = bytes(obj.data)
            else:
                raise TypeError(f"sha256 expects Bytes or StrValue, got {type(obj).__name__}")
        elif isinstance(data_val, StrValue):
            data = data_val.value.encode("utf-8")
        else:
            raise TypeError(f"sha256 expects Bytes or StrValue, got {type(data_val).__name__}")
        h = _sha256(data)
        return IntValue(h)
    env.define("sha256", BuiltinFunc("sha256", 1, _sha256_wrapper))

    # format(str, file_or_fd?) → StrValue
    def _format_wrapper(args):
        if len(args) < 1:
            raise TypeError("format() takes at least 1 argument")
        template = args[0]
        out_file = args[1] if len(args) > 1 else None

        from interp.eval import unwrap_optional
        from interp.value import Value

        def _fmt_arg(arg):
            """Format a single argument for the format string."""
            uv = unwrap_optional(arg)
            if isinstance(uv, IntValue):
                # Detect hash values (large integers ≈ 256 bits) and format as hex.
                if uv.value.bit_length() > 32 or uv.value < 0:
                    return format(uv.value, "x")
                return str(uv.value)
            if isinstance(uv, BoolValue):
                return "true" if uv.value else "false"
            if isinstance(uv, StrValue):
                return uv.value
            # For ObjectValue wrapping non-Value Python objects (like int fd), unwrap it.
            if isinstance(uv, ObjectValue) and not isinstance(uv.obj, Value):
                uv_inner = uv.obj  # This is a native Python value like int or str
                if isinstance(uv_inner, int):
                    return format(uv_inner, "x") if uv_inner.bit_length() > 32 else str(uv_inner)
            if isinstance(uv, ObjectValue):
                obj = uv.obj
                if hasattr(obj, "data"):  # Bytes
                    return f"<bytes {len(obj.data)}>"
                return f"<{type(obj).__name__}>"
            return str(uv)

        parts = [_fmt_arg(args[0])]  # Always include the template/first arg
        # Include args[2:] as additional formatted values (args[1] is file/fd destination)
        for arg in args[2:]:
            parts.append(_fmt_arg(arg))

        result_str = "".join(parts)
        # Only append newline when writing to an output destination.
        if out_file is not None:
            result_str += "\n"

        if out_file is not None:
            unwrapped_out = unwrap_optional(out_file)
            fd = 1  # default to stdout
            if isinstance(unwrapped_out, int):
                fd = unwrapped_out
            elif hasattr(unwrapped_out, "_fd"):
                fd = unwrapped_out._fd
            os.write(fd, result_str.encode("utf-8"))

        return StrValue(result_str)
    env.define("format", BuiltinFunc("format", -1, _format_wrapper))

    # get_stdout() → StdoutFile wrapped as ObjectValue
    def _get_stdout_wrapper(args):
        if len(args) != 0:
            raise TypeError("get_stdout() takes no arguments")
        return ObjectValue(std._stdout_file)
    env.define("get_stdout", BuiltinFunc("get_stdout", 0, _get_stdout_wrapper))


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
