"""Output-capture test runner for the NGPL interpreter.

Runs NGPL test programs and compares their stderr/stdout against
corresponding .expected files.  Each test is a pair:

    tests/output/test_name.ngpl     -- the source program
    tests/output/test_name.expected -- expected stderr output

Three optional files control how the program is invoked and checked:

    tests/output/test_name.args     -- one program argument per line,
                                       passed after the -- separator
    tests/output/test_name.env      -- one NAME=VALUE per line, added to
                                       the environment of the child
    tests/output/test_name.status   -- the expected exit status.  A
                                       process killed by signal N is
                                       reported as 128+N, as a shell
                                       reports it.  Without this file the
                                       exit status is not checked.

The test runner strips ANSI escape sequences before comparison
so tests work regardless of terminal settings.

Exit code is 0 if all tests pass, 1 otherwise.
"""

# The extension NGPL source files carry.
SOURCE_EXT = ".ngpl"

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


def _no_core_dumps():
    """Stop a deliberately aborted test from leaving a core file behind."""
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _read_lines(path: str) -> list[str]:
    """Read a sidecar file as a list of lines, or [] when it does not exist.

    The final newline is not treated as introducing an empty last entry,
    but interior blank lines are preserved so that an empty argument or
    an empty variable value can be expressed.
    """
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if text.endswith("\n"):
        text = text[:-1]
    if not text:
        return []
    return text.split("\n")


def run_test(src_path: str, expected_path: str) -> tuple[bool, str]:
    """Run a single output test, return (passed, detail_message)."""
    top_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rel_path = os.path.relpath(src_path, top_dir)
    base = src_path[:-len(SOURCE_EXT)]

    cmd = [sys.executable, "-m", "interp", rel_path]
    prog_args = _read_lines(base + ".args")
    if prog_args:
        cmd.append("--")
        cmd.extend(prog_args)

    child_env = dict(os.environ)
    for entry in _read_lines(base + ".env"):
        name, sep, value = entry.partition("=")
        if sep:
            child_env[name] = value

    # A program's own output and the interpreter's diagnostics go to
    # different streams but interleave in a way the test cares about, so
    # merge them in the child rather than concatenating two captures.
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=top_dir,
        env=child_env,
        preexec_fn=_no_core_dumps,
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
    max_lines = max(len(lines_actual), len(lines_expected))
    for i in range(max_lines):
        a = lines_actual[i] if i < len(lines_actual) else "<missing>"
        e = lines_expected[i] if i < len(lines_expected) else "<missing>"
        if a != e:
            diffs.append(f"  line {i + 1}:")
            diffs.append(f"    expected: {e!r}")
            diffs.append(f"    actual:   {a!r}")
    return False, "\n".join(diffs)


def main():
    test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    if not os.path.isdir(test_dir):
        print(f"No output test directory: {test_dir}", file=sys.stderr)
        sys.exit(1)

    tests: list[tuple[str, str]] = []
    for name in sorted(os.listdir(test_dir)):
        if name.endswith(SOURCE_EXT):
            base = name[:-len(SOURCE_EXT)]
            expected = os.path.join(test_dir, base + ".expected")
            if os.path.isfile(expected):
                tests.append((os.path.join(test_dir, name), expected))

    if not tests:
        print("No output tests found", file=sys.stderr)
        sys.exit(1)

    passed = 0
    failed = 0
    print(f"\nrunning {len(tests)} output tests", file=sys.stderr)

    for src_path, expected_path in tests:
        name = os.path.basename(src_path)[:-len(SOURCE_EXT)]
        ok, detail = run_test(src_path, expected_path)
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
