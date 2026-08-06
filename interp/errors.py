"""Error display for the newlang interpreter.

Formats error messages with source context, line/column indicators,
and optional syntax highlighting, similar to modern compilers like
gcc/clang/rustc.
"""

import sys


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

    if end_col is None or end_col <= col:
        end_col = col + 1

    end_col = min(end_col, len(src_line) + 1)
    underline_len = max(end_col - col, 1)

    max_line = line + 1 if line < len(lines) else line
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

    loc = f"{source_path}:{line}:{col + 1}"
    arrow_pad = " " * max(num_width - 1, 0)
    parts.append(
        f" {arrow_pad}{c.blue}{c.bold}-->{c.reset} {loc}"
    )

    parts.append(blank_gutter)

    line_num_str = str(line).rjust(num_width)
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
        ctx_num = str(line + 1).rjust(num_width)
        ctx_highlighted = _highlight_line(ctx_line, c)
        parts.append(
            f" {c.blue}{c.bold}{ctx_num} |{c.reset} {ctx_highlighted}"
        )

    parts.append(blank_gutter)

    return "\n".join(parts)


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
