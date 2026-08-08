"""REPL test runner for the NGPL interpreter.

Each test is a pair of files:

    tests/repl/test_name.repl     -- lines fed to the REPL on stdin
    tests/repl/test_name.expected -- expected stdout + stderr

Two optional files select what the REPL starts from and what status it
must end with:

    tests/repl/test_name.argv     -- interpreter arguments, one per line
                                     (e.g. a source file to preload, --repl)
    tests/repl/test_name.status   -- the expected exit status.  A session
                                     killed by signal N is reported as
                                     128+N, as a shell reports it.

With no .argv file the interpreter is run with no arguments at all, which
is the "no source file" entry into the REPL.

Because stdin is a pipe rather than a terminal, the REPL prints no banner
and no prompts, so the expected files hold only the results.

Exit code is 0 if all tests pass, 1 otherwise.
"""

import os
import re
import subprocess
import sys


# Same scheme as the interpreter's own test report, so a run reads as one
# thing.  Colour only when stderr is a terminal; a captured run stays
# plain.
if sys.stderr.isatty():
    _GREEN = "\033[32m"
    _RED = "\033[31m"
    _BOLD = "\033[1m"
    _RESET = "\033[0m"
else:
    _GREEN = _RED = _BOLD = _RESET = ""

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _read_lines(path: str) -> list[str]:
    """Read a sidecar file as a list of lines, or [] when it does not exist."""
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if text.endswith("\n"):
        text = text[:-1]
    if not text:
        return []
    return text.split("\n")


def run_test(repl_path: str, expected_path: str) -> tuple[bool, str]:
    """Run a single REPL test, return (passed, detail_message)."""
    top_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = repl_path[:-5]

    with open(repl_path, "r", encoding="utf-8") as f:
        stdin_text = f.read()

    cmd = [sys.executable, "-m", "interp"]
    cmd.extend(_read_lines(base + ".argv"))

    # Results go to stdout and diagnostics to stderr, and a test cares
    # about the order they were produced in, so merge them in the child
    # rather than concatenating two separately captured streams.
    result = subprocess.run(
        cmd,
        input=stdin_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=top_dir,
    )

    actual = strip_ansi(result.stdout).rstrip("\n")

    with open(expected_path, "r", encoding="utf-8") as f:
        expected = f.read().rstrip("\n")

    status_lines = _read_lines(base + ".status")
    if status_lines:
        # subprocess reports death by signal N as -N; a shell reports the
        # same thing as 128+N, which is what a test file states.
        actual_status = result.returncode
        if actual_status < 0:
            actual_status = 128 - actual_status
        expected_status = int(status_lines[0])
        if actual_status != expected_status:
            return False, (f"  exit status:\n"
                           f"    expected: {expected_status}\n"
                           f"    actual:   {actual_status}")

    if actual == expected:
        return True, ""

    lines_actual = actual.splitlines()
    lines_expected = expected.splitlines()
    diffs: list[str] = []
    for i in range(max(len(lines_actual), len(lines_expected))):
        a = lines_actual[i] if i < len(lines_actual) else "<missing>"
        e = lines_expected[i] if i < len(lines_expected) else "<missing>"
        if a != e:
            diffs.append(f"  line {i + 1}:")
            diffs.append(f"    expected: {e!r}")
            diffs.append(f"    actual:   {a!r}")
    return False, "\n".join(diffs)


def main():
    test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "repl")
    if not os.path.isdir(test_dir):
        print(f"No REPL test directory: {test_dir}", file=sys.stderr)
        sys.exit(1)

    tests: list[tuple[str, str]] = []
    for name in sorted(os.listdir(test_dir)):
        if name.endswith(".repl"):
            expected = os.path.join(test_dir, name[:-5] + ".expected")
            if os.path.isfile(expected):
                tests.append((os.path.join(test_dir, name), expected))

    if not tests:
        print("No REPL tests found", file=sys.stderr)
        sys.exit(1)

    passed = 0
    failed = 0
    print(f"\nrunning {len(tests)} REPL tests", file=sys.stderr)

    for repl_path, expected_path in tests:
        name = os.path.basename(repl_path)[:-5]
        ok, detail = run_test(repl_path, expected_path)
        if ok:
            print(f"test {name} ... {_GREEN}ok{_RESET}", file=sys.stderr)
            passed += 1
        else:
            print(f"test {name} ... {_RED}{_BOLD}FAILED{_RESET}",
                  file=sys.stderr)
            print(detail, file=sys.stderr)
            failed += 1

    status = (f"{_GREEN}ok{_RESET}" if failed == 0
              else f"{_RED}{_BOLD}FAILED{_RESET}")
    print(f"\ntest result: {status}. {passed} passed; {failed} failed\n",
          file=sys.stderr)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
