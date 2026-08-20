"""Error display for the NGPL interpreter.

Formats error messages with source context, line/column indicators,
and optional syntax highlighting, similar to modern compilers like
gcc/clang/rustc.
"""

import sys


class ProgramExit(BaseException):
    """Raised by std.exit to terminate the interpreted program.

    Derived from BaseException rather than Exception so that a `catch`
    statement, an @expect-annotated function, or any other broad
    ``except Exception`` in the evaluator does not swallow a request to
    terminate.  This is the same reason Python's SystemExit sits outside
    the Exception hierarchy.
    """

    def __init__(self, code: int):
        self.code = code
        super().__init__(f"exit({code})")


class ProgramAbort(BaseException):
    """Raised by std.abort to terminate the program with a signal.

    Carries the signal number rather than raising it at once so that the
    interpreter can print a backtrace before the process dies.
    """

    def __init__(self, signal_number: int):
        self.signal_number = signal_number
        super().__init__(f"abort(signal {signal_number})")


# Whether a warning is to be treated as an error, as -Werror asks.
# Set once from the command line and read wherever a diagnostic's level
# is decided, so the option reaches the @expect machinery as well as
# the text that is printed.
_warnings_are_errors = False


def set_warnings_are_errors(on: bool) -> None:
    """Make every warning an error, or stop doing so."""
    global _warnings_are_errors
    _warnings_are_errors = on


def warnings_are_errors() -> bool:
    """Whether warnings are being treated as errors."""
    return _warnings_are_errors


# What a @pre or a @post that does not hold does, named as C++26 names
# the four evaluation semantics.  Set once from the command line and
# read where a condition is checked.
CONTRACT_SEMANTICS = ("ignore", "observe", "enforce", "quick-enforce")

_contract_semantic = "enforce"


def set_contract_semantic(name: str) -> None:
    """Choose what a condition that does not hold does."""
    global _contract_semantic
    if name not in CONTRACT_SEMANTICS:
        raise ValueError(f"unknown contract semantic: {name}")
    _contract_semantic = name


def contract_semantic() -> str:
    """What a condition that does not hold does."""
    return _contract_semantic


# The text the program was loaded from, so that something reported
# while it runs can show the line it happened on.  An error reaches the
# top level and is formatted there against the source main() holds; a
# diagnostic the run carries on past never reaches it, so the source is
# left here for it to find.
_source_text: str = ""
_source_path: str = "<unknown>"

# Where each source file begins in the concatenated text, as a line
# number, beside the name of the file that begins there.  One file
# leaves these empty and every line is simply its own.
_file_starts: list[int] = []
_file_names: list[str] = []


def set_source(text: str, path: str,
               starts: list[int] | None = None,
               names: list[str] | None = None) -> None:
    """Register the source a diagnostic raised mid-run points into.

    Several files are read as one, so a line number counted from the
    start of the whole text is not the line number anybody wrote.
    `starts` and `names` say where each file began, which is what turns
    the one back into the other.
    """
    global _source_text, _source_path, _file_starts, _file_names
    _source_text = text
    _source_path = path
    _file_starts = list(starts or [])
    _file_names = list(names or [])


def locate(line: int, fallback: str) -> tuple[str, int]:
    """Say which file a line of the concatenated source came from.

    Answers the file's name and the line number within it.  With one
    file, or none registered, the line is already what it should be.
    """
    if len(_file_starts) < 2:
        return fallback, line
    # The file a line belongs to is the last one that begins at or
    # before it.  A source is a handful of files, so a walk from the
    # back finds it in fewer steps than the search would take to set up.
    for k in range(len(_file_starts) - 1, -1, -1):
        if line >= _file_starts[k]:
            return _file_names[k], line - _file_starts[k] + 1
    return fallback, line


class _StackHolder:
    """Something to hang a call stack on, for the backtrace formatter.

    A backtrace is ordinarily read off the exception that carried it up
    to the top level.  A diagnostic the run carries on past has no
    exception, so it borrows one of these.
    """


def report_runtime_diagnostic(message: str,
                              pos: tuple[int, int, int | None] | None = None,
                              *, level: str = "warning",
                              call_stack=()) -> None:
    """Print something found while the program runs, and carry on.

    Points into the registered source where the position falls inside
    it, and says the message on its own where it does not -- the same
    fallback the install-time warnings use.
    """
    if _source_text and pos is not None \
            and pos[0] <= _source_text.count("\n") + 1:
        print(format_diagnostic(_source_text, _source_path, pos[0], pos[1],
                                message, end_col=pos[2], level=level),
              file=sys.stderr)
    else:
        print(f"{level}: {message}", file=sys.stderr)
    if call_stack:
        holder = _StackHolder()
        attach_backtrace(holder, call_stack)
        trace = format_backtrace(holder, _source_path)
        if trace is not None:
            print(trace, file=sys.stderr)


def diagnostic_level(level: str) -> str:
    """The level a diagnostic is reported at.

    Under -Werror a warning is an error, in what is printed and in what
    an @expect has to say to match it: an annotation written
    `@expect warning` is read as `@expect error`, so a source file that
    accounts for its diagnostics needs no rewriting to be checked this
    way.
    """
    return "error" if _warnings_are_errors and level == "warning" else level


def attach_backtrace(exc: BaseException, call_stack: list) -> None:
    """Record the interpreted program's call stack on an exception.

    Called at the innermost frame that sees the exception, so the stack
    is captured before it unwinds.  A later frame finds the attribute
    already set and leaves it alone.  Attaching it to the exception
    rather than keeping it on the evaluator means a stack can never be
    reported against the wrong failure.
    """
    if getattr(exc, "_ngpl_backtrace", None) is not None:
        return
    try:
        exc._ngpl_backtrace = [list(frame) for frame in call_stack]
    except AttributeError:
        pass  # a few builtin exception types reject attribute assignment


def format_backtrace(exc: BaseException, source_path: str, *,
                     min_frames: int = 2) -> str | None:
    """Render the call stack recorded on an exception, innermost first.

    Only the interpreted program's functions appear.  The interpreter's
    own Python frames are a separate thing, shown by
    --interpreter-backtrace.

    Args:
        exc: the exception carrying the recorded stack.
        source_path: the file the program was loaded from.
        min_frames: the shortest stack worth printing.  The default of
            two suppresses the single-frame case, where the backtrace
            would only repeat the location the diagnostic's caret has
            already pointed at.  Callers with no diagnostic of their own
            to show pass one.

    Returns:
        The formatted backtrace, or None when there is nothing useful to
        show.
    """
    frames = getattr(exc, "_ngpl_backtrace", None)
    if not frames or len(frames) < min_frames:
        return None
    c = _Colors(_is_tty())
    lines = [f"{c.bold}backtrace{c.reset} (innermost call first):"]
    for depth, frame in enumerate(reversed(frames)):
        name, pos, label = frame[0], frame[1], frame[2]
        if pos is None:
            where = label if label is not None else source_path
        else:
            # a frame's line is counted over the whole text, so it says
            # which of the source files it fell in, as a diagnostic does
            origin, line = locate(pos[0], source_path)
            where = f"{label or origin}:{line}:{pos[1]}"
        lines.append(f"  #{depth} {c.bold}{name}{c.reset} at {where}")
    return "\n".join(lines)


def _is_tty() -> bool:
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


class _Colors:
    """ANSI escape sequences for terminal coloring."""

    def __init__(self, enabled: bool):
        if enabled:
            self.reset = "\033[0m"
            self.bold = "\033[1m"
            self.red = "\033[31m"
            self.green = "\033[32m"
            self.yellow = "\033[33m"
            self.blue = "\033[34m"
            self.magenta = "\033[35m"
            self.cyan = "\033[36m"
            self.white = "\033[37m"
            self.dim = "\033[2m"
        else:
            self.reset = ""
            self.bold = ""
            self.red = ""
            self.green = ""
            self.yellow = ""
            self.blue = ""
            self.magenta = ""
            self.cyan = ""
            self.white = ""
            self.dim = ""


_HIGHLIGHT_KEYWORDS = frozenset({
    "fn", "var", "if", "else", "elif", "while", "return", "const",
    "foreach", "true", "false", "and", "or", "not", "some", "enum",
    "flag", "unit", "catch", "match", "import", "let", "comptime",
})


def _highlight_line(line: str, c: _Colors) -> str:
    """Apply syntax highlighting to a source line."""
    if not c.bold:
        return line
    result: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == '"':
            j = i + 1
            while j < n and line[j] != '"':
                if line[j] == '\\' and j + 1 < n:
                    j += 1
                j += 1
            j = min(j + 1, n)
            result.append(f"{c.green}{line[i:j]}{c.reset}")
            i = j
        elif ch.isdigit():
            j = i + 1
            while j < n and (line[j].isdigit() or line[j] in "._xXabcdefABCDEF"):
                j += 1
            result.append(f"{c.cyan}{line[i:j]}{c.reset}")
            i = j
        elif ch.isalpha() or ch == '_':
            j = i + 1
            while j < n and (line[j].isalnum() or line[j] in "_'"):
                j += 1
            word = line[i:j]
            if word in _HIGHLIGHT_KEYWORDS:
                result.append(f"{c.magenta}{c.bold}{word}{c.reset}")
            elif word == "@start" or word == "@test":
                result.append(f"{c.yellow}{word}{c.reset}")
            else:
                result.append(word)
            i = j
        elif ch == '@' and i + 1 < n and line[i + 1].isalpha():
            j = i + 1
            while j < n and (line[j].isalnum() or line[j] in "_'"):
                j += 1
            word = line[i:j]
            result.append(f"{c.yellow}{word}{c.reset}")
            i = j
        elif ch == '/' and i + 1 < n and line[i + 1] == '/':
            result.append(f"{c.dim}{line[i:]}{c.reset}")
            i = n
        elif ch == '/' and i + 1 < n and line[i + 1] == '*':
            result.append(f"{c.dim}{line[i:]}{c.reset}")
            i = n
        else:
            result.append(ch)
            i += 1
    return "".join(result)


def format_diagnostic(
    source: str,
    source_path: str,
    line: int,
    col: int,
    message: str,
    *,
    end_col: int | None = None,
    level: str = "error",
    use_color: bool | None = None,
) -> str:
    """Format a compiler/interpreter diagnostic with source context.

    Args:
        source: the full source text.
        source_path: path to the source file (for display).
        line: 1-based line number of the error.
        col: 0-based column of the error start.
        message: the error message.
        end_col: 0-based column past the end of the error region.
        level: "error", "warning", or "note".
        use_color: force color on/off; None = auto-detect from stderr.
    """
    if use_color is None:
        use_color = _is_tty()
    c = _Colors(use_color)

    lines = source.splitlines()
    if line < 1:
        level_str = f"{c.red}{c.bold}{level}{c.reset}" if level == "error" else f"{c.yellow}{c.bold}{level}{c.reset}"
        return f"{level_str}: {c.bold}{message}{c.reset}"
    if line > len(lines):
        line = len(lines)
        if line < 1:
            level_str = f"{c.red}{c.bold}{level}{c.reset}" if level == "error" else f"{c.yellow}{c.bold}{level}{c.reset}"
            return f"{level_str}: {c.bold}{message}{c.reset}"
        col = len(lines[line - 1])
        end_col = col + 1

    src_line = lines[line - 1]

    # `line` indexes the whole text, which is where the excerpt comes
    # from; what is shown is the file that text belongs to and the line
    # number within it, which is what somebody reading the error has in
    # front of them.
    shown_path, shown_line = locate(line, source_path)

    if end_col is None or end_col <= col:
        end_col = col + 1

    end_col = min(end_col, len(src_line) + 1)
    underline_len = max(end_col - col, 1)

    max_line = shown_line + 1 if line < len(lines) else shown_line
    num_width = max(len(str(max_line)), 2)

    level_colors = {
        "error": c.red,
        "warning": c.yellow,
        "note": c.blue,
    }
    level_color = level_colors.get(level, c.red)

    blank_gutter = f" {' ' * num_width} {c.blue}{c.bold}|{c.reset}"

    parts: list[str] = []

    parts.append(
        f"{level_color}{c.bold}{level}{c.reset}{c.bold}: {message}{c.reset}"
    )

    loc = f"{shown_path}:{shown_line}:{col + 1}"
    arrow_pad = " " * max(num_width - 1, 0)
    parts.append(
        f" {arrow_pad}{c.blue}{c.bold}-->{c.reset} {loc}"
    )

    parts.append(blank_gutter)

    line_num_str = str(shown_line).rjust(num_width)
    highlighted = _highlight_line(src_line, c)
    parts.append(
        f" {c.blue}{c.bold}{line_num_str} |{c.reset} {highlighted}"
    )

    pad = " " * col
    carets = "^" * underline_len
    parts.append(
        f"{blank_gutter} {pad}{level_color}{c.bold}{carets}{c.reset}"
    )

    if line < len(lines):
        ctx_line = lines[line]
        ctx_num = str(shown_line + 1).rjust(num_width)
        ctx_highlighted = _highlight_line(ctx_line, c)
        parts.append(
            f" {c.blue}{c.bold}{ctx_num} |{c.reset} {ctx_highlighted}"
        )

    parts.append(blank_gutter)

    return "\n".join(parts)


class ContractError(Exception):
    """A condition a function said it holds to did not hold.

    Carries the position of the condition rather than of whatever the
    function was doing when it broke, so the reader is shown the claim
    that failed: the sentence they wrote about what should be true.
    """

    def __init__(self, message, pos=None):
        super().__init__(message)
        self.pos = pos
        if pos is not None:
            self.line, self.col, self.end_col = pos


def extract_position(exc: BaseException) -> tuple[int, int, int | None] | None:
    """Extract (line, col, end_col) from an exception if it carries position.

    Returns None if no position information is available.
    """
    if hasattr(exc, "line") and hasattr(exc, "col"):
        return (exc.line, exc.col, getattr(exc, "end_col", None))
    msg = str(exc)
    import re
    m = re.match(r"Line (\d+), col (\d+): ", msg)
    if m:
        return (int(m.group(1)), int(m.group(2)), None)
    return None


def strip_position_prefix(msg: str) -> str:
    """Remove 'Line N, col M: ' prefix from an error message."""
    import re
    return re.sub(r"^Line \d+, col \d+: ", "", msg)
