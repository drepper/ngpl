#!/usr/bin/env python3
"""Put the new wording into the expectations that recorded the old.

An `@expect` names the diagnostic by number and states the message
beside it.  The number is what is matched; the message is what the
diagnostic said when the expectation was written, and a diagnostic is
allowed to say it better later.  When it does, the run records the
drift rather than failing -- one JSON line per expectation, saying
which file and line it is on, which number, what it said and what it
says now.

This reads those lines and rewrites the expectations.  Nobody has to
read a message to keep the suite green, which is the point: the words
are free to improve.

    python -m interp --expect-drift=drift.jsonl tests/whatever.ngpl
    tools/update_expectations.py drift.jsonl

With --dry-run it says what it would change and changes nothing.
"""

import argparse
import json
import re
import sys
from collections import defaultdict


def _escape(message: str) -> str:
    """The message as an NGPL string literal's contents."""
    return message.replace("\\", "\\\\").replace('"', '\\"')


def _apply(path: str, drifts: list, dry_run: bool) -> int:
    """Rewrite one file's expectations.  Answers how many changed."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as e:
        print(f"{path}: {e}", file=sys.stderr)
        return 0

    changed = 0
    for drift in drifts:
        line_no = drift.get("line")
        if not isinstance(line_no, int) or not 1 <= line_no <= len(lines):
            print(f"{path}: line {line_no} is not in the file", file=sys.stderr)
            continue
        line = lines[line_no - 1]
        # @expect <level> <code> "message" -- the code is matched
        # against the record so a line that has since moved or been
        # rewritten is left alone rather than overwritten blindly.
        m = re.match(r'^(\s*@expect\s+(?:error|warning)\s+(\d+)\s+)"(.*)"\s*$',
                     line)
        if m is None:
            print(f"{path}:{line_no}: not an @expect with a code and a "
                  f"message; left alone", file=sys.stderr)
            continue
        if int(m.group(2)) != drift.get("code"):
            print(f"{path}:{line_no}: expects {m.group(2)} and the record "
                  f"says {drift.get('code')}; left alone", file=sys.stderr)
            continue
        new_line = f'{m.group(1)}"{_escape(drift["says"])}"\n'
        if new_line == line:
            continue
        if dry_run:
            print(f"{path}:{line_no}: would say \"{drift['says']}\"")
        else:
            lines[line_no - 1] = new_line
        changed += 1

    if changed and not dry_run:
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        print(f"{path}: {changed} expectation"
              f"{'' if changed == 1 else 's'} brought up to date")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("drift", nargs="+", metavar="FILE",
                    help="a file --expect-drift wrote")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would change and change nothing")
    args = ap.parse_args()

    by_file = defaultdict(list)
    seen = set()
    for name in args.drift:
        try:
            with open(name, encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    record = json.loads(raw)
                    key = (record["file"], record["line"], record["code"])
                    if key in seen:
                        continue
                    seen.add(key)
                    by_file[record["file"]].append(record)
        except OSError as e:
            print(f"{name}: {e}", file=sys.stderr)
            return 2

    # Later lines first, so rewriting one does not move the next.  They
    # are the same length in lines, but a file that gains a line one day
    # should not need this thought again.
    total = 0
    for path, drifts in sorted(by_file.items()):
        drifts.sort(key=lambda d: d["line"], reverse=True)
        total += _apply(path, drifts, args.dry_run)

    if total == 0:
        print("nothing had drifted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
