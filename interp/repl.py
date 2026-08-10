"""Interactive read-eval-print loop for the NGPL interpreter.

The REPL accepts everything a source file may contain — function,
variable, type, unit, enum, struct, and impl definitions — and in
addition the statements and expressions that a file may not have at top
level.  A bare expression is evaluated and its value shown.

Input is read a line at a time and accumulated until it forms something
complete.  Two rules decide when that is:

  * A single line is complete when it parses.  A line that ends in the
    middle of a bracket, a string, or an expression continues.
  * Once a layout block is opened — an indented body follows a line
    ending in ':' — input continues until an empty line, even though the
    block would already parse.  Without this rule there would be no way
    to add a second statement to a function body.
"""

import sys

from interp.env import Env
from interp.errors import (extract_position, format_backtrace,
                           format_diagnostic, strip_position_prefix,
                           ProgramAbort, ProgramExit)
from interp.eval import Evaluator
from interp.lexer import process_indentation, tokenize
from interp.parser import ParseError, Parser
from interp.ast import (
    EnumDef as ASTEnumDef,
    ExprStmt,
    FuncDef as ASTFuncDef,
    ImplBlock as ASTImplBlock,
    StructDef as ASTStructDef,
    TypeDef as ASTTypeDef,
    UnitDef as ASTUnitDef,
    VarDef as ASTVarDef,
)
from interp.value import NoneValue, Value

PROMPT = ">>> "
CONTINUATION_PROMPT = "... "

_DEFINITION_NODES = (ASTFuncDef, ASTVarDef, ASTEnumDef, ASTStructDef,
                     ASTImplBlock, ASTUnitDef, ASTTypeDef)


def _error_message(exc: BaseException) -> str:
    """Extract a diagnostic message from an exception.

    KeyError stringifies to its argument's repr, which would wrap an
    already-complete message in stray quotes.
    """
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc)


def _needs_more_input(src: str) -> bool:
    """Report whether accumulated input is still waiting to be completed.

    Args:
        src: everything typed so far for the current entry, newline-joined.

    Returns:
        True when the REPL should read another line.
    """
    lines = src.split("\n")

    # An empty line always ends a multi-line entry.  This is what closes
    # a layout block, and it also provides an escape from input the
    # heuristics below would otherwise keep waiting on.
    if len(lines) > 1 and lines[-1].strip() == "":
        return False

    if not src.strip():
        return False

    try:
        tokens = process_indentation(tokenize(src))
    except Exception:
        # An unterminated string literal is the common case here.
        return True

    significant = [t for t in tokens
                   if t.type not in ("NEWLINE", "INDENT", "DEDENT", "EOF")]
    if not significant:
        return False

    # A line ending in ':' or '{' opens a block whose body is still to come.
    last = significant[-1]
    if last.type == "PUNCT" and last.value in (":", "{"):
        return True

    # A layout block was opened and its body has begun.  It parses, but
    # more statements may still be intended, so wait for the empty line.
    if any(t.type == "INDENT" for t in tokens):
        return True

    try:
        items = Parser(tokens).parse_repl()
    except ParseError as e:
        # An error at the very end means the input simply stops early;
        # an error anywhere else is a real syntax error to report now.
        return e.token is not None and e.token.type == "EOF"
    except Exception:
        return False

    # Tokens that parse to nothing are annotations — @test, @start — still
    # waiting for the definition they apply to.
    return not items


def _display_with_type(value) -> str:
    """Render a value for the prompt, saying what type a number is.

    A number's type is the thing hardest to see and easiest to be
    wrong about, so the prompt says it, spelled as the suffix that
    would produce it.  An untyped literal has no suffix to name and is
    left as written.
    """
    from interp.value import IntValue, FloatValue, UnitValue
    if isinstance(value, UnitValue):
        return f"{_display_with_type(value.inner)} {value.unit.display_name}"
    if isinstance(value, IntValue):
        return value.display() if value.width == "int" else f"{value.display()}{value.width}"
    if isinstance(value, FloatValue):
        return value.display() if value.width == "float" else f"{value.display()}{value.width}"
    return value.display()


class Repl:
    """The interactive interpreter session.

    Bindings accumulate in a single environment, so a function defined
    in one entry is callable from the next.
    """

    def __init__(self, env: Env, evaluator: Evaluator):
        self.env = env
        self.evaluator = evaluator
        self._entry = 0
        # Prompts and the banner are for a person at a terminal.  Piped
        # input gets neither, so its output is exactly the results.
        self._interactive = sys.stdin.isatty()

    def run(self) -> int:
        """Read, evaluate, and print until end of input.

        Returns:
            The process exit code.
        """
        if self._interactive:
            self._setup_line_editing()
            print("NGPL interpreter.  Ctrl-D to exit; end an indented block "
                  "with an empty line.", file=sys.stderr)

        buffer: list[str] = []
        while True:
            if not self._interactive:
                prompt = ""
            elif buffer:
                prompt = CONTINUATION_PROMPT
            else:
                prompt = PROMPT
            try:
                line = input(prompt)
            except EOFError:
                if self._interactive:
                    print(file=sys.stderr)
                return 0
            except KeyboardInterrupt:
                # Abandon the entry in progress, like Python's REPL.
                print("\nKeyboardInterrupt", file=sys.stderr)
                buffer = []
                continue

            buffer.append(line)
            src = "\n".join(buffer)
            if _needs_more_input(src):
                continue

            buffer = []
            if src.strip():
                try:
                    self._run_entry(src)
                except ProgramExit as e:
                    return e.code
                except ProgramAbort as e:
                    self._abort(e)

    @staticmethod
    def _setup_line_editing():
        """Enable readline editing and history when the module is available."""
        try:
            import readline  # noqa: F401  -- importing installs the hook
        except ImportError:
            pass

    def _run_entry(self, src: str):
        """Parse and evaluate one complete entry, reporting any error."""
        self._entry += 1
        name = f"<repl:{self._entry}>"
        try:
            items = Parser(process_indentation(tokenize(src))).parse_repl()
        except Exception as e:
            self._show_error(e, src, name)
            return

        try:
            for item in items:
                self._eval_item(item)
        except KeyboardInterrupt:
            print("\nKeyboardInterrupt", file=sys.stderr)
        except (SystemExit, ProgramExit, ProgramAbort):
            # Terminating the program terminates the session with it.
            raise
        except Exception as e:
            self._show_error(e, src, name)

    def _eval_item(self, item):
        """Install a definition or evaluate a statement, showing any value."""
        from interp.__main__ import install_definitions

        if isinstance(item, _DEFINITION_NODES):
            program = install_definitions([item], self.env, self.evaluator,
                                          honor_start=False)
            self._label_definition(item)
            self._report_definition(item, program)
            return

        result = self.evaluator.eval_stmt(item)
        # Only a bare expression reports a value; a statement that happens
        # to end in an expression stays quiet, as it would in a file.
        if isinstance(item, ExprStmt) and isinstance(result, Value):
            if not isinstance(result, NoneValue):
                # std.print writes to fd 1 directly, so results must be
                # flushed to keep them in order with a program's output.
                print(_display_with_type(result), flush=True)

    def _label_definition(self, item):
        """Record which entry defined a function, for later backtraces.

        Line numbers in the REPL are relative to the entry the code was
        typed in, so a frame that named the current entry would point at
        the wrong text.
        """
        from interp.value import FuncValue, StructType

        label = f"<repl:{self._entry}>"
        if isinstance(item, ASTFuncDef):
            defined = self.env.lookup(item.name)
            if isinstance(defined, FuncValue):
                defined.source_label = label
        elif isinstance(item, ASTImplBlock):
            struct = self.env.lookup(item.struct_name)
            if isinstance(struct, StructType):
                for method in struct.methods.values():
                    if method.source_label is None:
                        method.source_label = label

    def _report_definition(self, item, program):
        """Acknowledge a definition and run any test it introduced."""
        from interp.__main__ import _run_test

        if isinstance(item, ASTFuncDef) and item.expect_annotations:
            print(f"note: @expect on '{item.name}' is checked when the file is "
                  f"run, not interactively", file=sys.stderr)
            return

        for test_fv in program.standalone_tests:
            ok, msg = _run_test(test_fv, self.env)
            if ok:
                print(f"test {test_fv.name} ... ok", file=sys.stderr)
            else:
                print(f"test {test_fv.name} ... FAILED", file=sys.stderr)
                print(f"  {msg}", file=sys.stderr)

    def _abort(self, exc: ProgramAbort):
        """Report an abort raised from the session, then deliver the signal."""
        import signal as _signal
        from interp.std import deliver_abort

        print(f"aborted: {_signal.Signals(exc.signal_number).name}",
              file=sys.stderr)
        trace = format_backtrace(exc, "<repl>", min_frames=1)
        if trace is not None:
            print(trace, file=sys.stderr)
        deliver_abort(exc.signal_number)

    def _show_error(self, exc: BaseException, src: str, name: str):
        """Print a diagnostic for an error raised while handling an entry."""
        pos = extract_position(exc)
        if pos is None:
            pos = self.evaluator._last_pos
        msg = strip_position_prefix(_error_message(exc))
        if isinstance(exc, AssertionError) and "assertion" not in msg.lower():
            msg = f"assertion failed: {msg}"

        if pos is not None:
            line, col, end_col = pos
            if line <= len(src.split("\n")):
                print(format_diagnostic(src, name, line, col, msg,
                                        end_col=end_col, level="error"),
                      file=sys.stderr)
            else:
                print(f"error: {msg}", file=sys.stderr)
        else:
            print(f"error: {msg}", file=sys.stderr)

        trace = format_backtrace(exc, name)
        if trace is not None:
            print(trace, file=sys.stderr)
