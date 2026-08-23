#!/usr/bin/env python3
"""The same program, laid out two ways, hashes its functions the same.

t60 indents its blocks and gives each statement a line; t61 writes the
same blocks in braces with several statements to a line.  They are the
same program, so every `function` row of the bill of materials must
carry the same digest -- and, since a bill is only worth reading if it
says where a difference is, the rows must be there at all.

Nothing either program prints could show this, which is why it is
checked here rather than by running them.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_elf_tests import Elf, sbom_rows


def functions(path: str) -> dict:
    """The function rows of one binary, by name."""
    with open(path, "rb") as fh:
        rows = sbom_rows(Elf(fh.read()))
    return {name: digest for kind, name, digest in rows
            if kind == "function"}


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: check_layout_hashes.py INDENTED BRACED", file=sys.stderr)
        return 2
    a, b = functions(sys.argv[1]), functions(sys.argv[2])
    bad = 0
    if not a:
        print("FAIL layout: the bill carries no function rows")
        return 1
    if set(a) != set(b):
        print(f"FAIL layout: the two name different functions: "
              f"{sorted(a)} and {sorted(b)}")
        return 1
    for name in sorted(a):
        if a[name] != b[name]:
            print(f"FAIL layout: '{name}' hashes {a[name][:16]} indented "
                  f"and {b[name][:16]} braced")
            bad += 1
    if bad:
        return 1
    print(f"ok   layout: {len(a)} functions hash the same however they "
          f"are laid out")
    return 0


if __name__ == "__main__":
    sys.exit(main())
