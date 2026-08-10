"""Check that every function signature the specification shows parses.

The specification is the normative reference, so an example in it that
the parser would refuse is a defect in the document.  Signatures drift
most easily of anything in it: the language once accepted them without
parentheses, the requirement changed, and sixty-three examples went on
saying the old thing because nothing ever read them.

Every `fn` line inside a fenced code block is extracted and parsed with
a stand-in body.  A signature is checked in isolation, so what is
verified is the signature rather than the example around it.

Exit code is 0 if all signatures parse, 1 otherwise.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interp.lexer import tokenize, process_indentation
from interp.parser import Parser


if sys.stderr.isatty():
    _GREEN, _RED, _BOLD, _RESET = "\033[32m", "\033[31m", "\033[1m", "\033[0m"
else:
    _GREEN = _RED = _BOLD = _RESET = ""


_HEAD = re.compile(r"^\s*fn\s+[A-Za-z_][A-Za-z0-9_']*")


def strip_noncode(text: str) -> str:
    """Blank out comments and string literals, keeping positions."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
            continue
        if text[i] == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append("".join(c if c == "\n" else " " for c in text[i:j]))
            i = j
            continue
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] not in ('"', "\n"):
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append("".join(c if c == "\n" else " " for c in text[i:j]))
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def signatures(path: str):
    """Yield (line number, signature text) for every fn line in a code block."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().split("\n")

    blocks, in_block, start = [], False, 0
    for no, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            if in_block:
                blocks.append((start, no - 1))
                in_block = False
            else:
                in_block, start = True, no

    for begin, end in blocks:
        body = lines[begin:end]
        cleaned = strip_noncode("\n".join(body)).split("\n")
        for offset, cleaned_line in enumerate(cleaned):
            if _HEAD.match(cleaned_line) is None:
                continue
            # The grammar production describes the syntax rather than
            # using it, so it is not a signature to parse.
            if "'('" in body[offset]:
                continue
            yield begin + offset + 1, cleaned_line.rstrip()


def as_program(signature: str) -> str | None:
    """Wrap a signature in the least code that makes it parseable.

    Returns None for a signature written with elisions, which stands
    for a shape rather than being one.
    """
    stripped = signature.strip()
    if "..." in stripped:
        return None
    # A brace body may run past the line; give the signature its own.
    brace = stripped.find("{")
    if brace != -1:
        stripped = stripped[:brace].rstrip() + ": \N{EMPTY SET}"
    elif stripped.endswith(":"):
        stripped += " \N{EMPTY SET}"
    elif ":" not in stripped:
        return None
    # A method taking self belongs to an impl block.
    if "self" in stripped.split(")")[0]:
        return ("struct S:\n    n : i32\n\nimpl S:\n    " + stripped + "\n")
    return stripped + "\n"


def main():
    top = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(top, "spec", "ngpl.md")
    rel = os.path.relpath(path, top)

    checked = skipped = 0
    failures: list[tuple[int, str, str]] = []
    for line_no, signature in signatures(path):
        program = as_program(signature)
        if program is None:
            skipped += 1
            continue
        try:
            Parser(process_indentation(tokenize(program))).parse()
            checked += 1
        except Exception as e:
            failures.append((line_no, signature.strip(), str(e)))

    print(f"\nchecking {checked + len(failures)} signatures in {rel}")
    for line_no, signature, message in failures:
        print(f"{_RED}{_BOLD}FAILED{_RESET} {rel}:{line_no}: {signature}")
        print(f"  {message}")

    if failures:
        print(f"\n{_RED}{_BOLD}signature check: FAILED.{_RESET} "
              f"{checked} passed; {len(failures)} failed")
        sys.exit(1)
    print(f"\n{_GREEN}{_BOLD}signature check: ok.{_RESET} "
          f"{checked} parsed; {skipped} elided")


if __name__ == "__main__":
    main()
