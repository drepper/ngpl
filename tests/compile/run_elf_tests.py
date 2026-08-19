#!/usr/bin/env python3
"""The invariants of the binaries ngplc writes.

The conformance suite compares what a compiled program *prints* against
what the interpreter prints.  That says nothing about the shape of the
file the program arrived in, and the shape is where a good deal of
hard-won work sits: the segment permissions, the RELRO region, the
non-executable stack, the symbol table's ordering and its signature
names, and the trimming that leaves an unreachable runtime routine out
of the binary altogether.  All of it was checked by hand with readelf
and nm when it landed, and nothing has checked it since.

This asserts it.  The file is parsed here rather than scraped out of
another tool's prose, so the checks can be exact and so the suite does
not depend on binutils being installed -- but where readelf *is*
present it is run as well, because a second reader that has never seen
this compiler is worth more than any assertion written beside it.

Two of the checks are here because of specific bugs.  A symbol whose
size ran past the next symbol went unnoticed for as long as the symbol
table has existed; `_start` was reported as most of the binary.  And a
compiler that wrote an empty file exited successfully, because from
its own side nothing had gone wrong -- it asked the kernel for zero
bytes and got zero bytes.  Overlap and emptiness are cheap to check
and neither would have survived it.
"""

import os
import shutil
import struct
import subprocess
import sys
import tempfile

PAGE = 4096
IMAGE_BASE = 0x400000

PT_LOAD = 1
PT_GNU_RELRO = 0x6474E552
PT_GNU_STACK = 0x6474E551
PF_X, PF_W, PF_R = 1, 2, 4

SHT_PROGBITS, SHT_SYMTAB, SHT_STRTAB = 1, 2, 3
SHF_WRITE, SHF_ALLOC, SHF_EXECINSTR = 1, 2, 4

STB_LOCAL, STB_GLOBAL = 0, 1
STT_FUNC = 2

topdir = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


class Failure(Exception):
    """One invariant that does not hold."""


class Elf:
    """As much of an ELF64 file as these invariants ask about."""

    def __init__(self, raw: bytes):
        self.raw = raw
        if len(raw) < 64:
            raise Failure(f"the file is {len(raw)} bytes; a header alone is 64")
        self.ident = raw[:16]
        (self.e_type, self.e_machine, self.e_version, self.e_entry,
         self.e_phoff, self.e_shoff, self.e_flags, self.e_ehsize,
         self.e_phentsize, self.e_phnum, self.e_shentsize, self.e_shnum,
         self.e_shstrndx) = struct.unpack_from("<HHIQQQIHHHHHH", raw, 16)
        self.phdrs = [
            dict(zip(("type", "flags", "offset", "vaddr", "paddr",
                      "filesz", "memsz", "align"),
                     struct.unpack_from("<IIQQQQQQ", raw,
                                        self.e_phoff + i * 56)))
            for i in range(self.e_phnum)]
        self.shdrs = [
            dict(zip(("name", "type", "flags", "addr", "offset", "size",
                      "link", "info", "addralign", "entsize"),
                     struct.unpack_from("<IIQQQQIIQQ", raw,
                                        self.e_shoff + i * 64)))
            for i in range(self.e_shnum)]
        shstr = self.shdrs[self.e_shstrndx]
        self.shstrtab = raw[shstr["offset"]:shstr["offset"] + shstr["size"]]
        for sh in self.shdrs:
            sh["sname"] = self._str(self.shstrtab, sh["name"])

    @staticmethod
    def _str(table: bytes, at: int) -> str:
        end = table.index(b"\0", at)
        return table[at:end].decode("utf-8", "replace")

    def section(self, name: str) -> dict:
        for sh in self.shdrs:
            if sh["sname"] == name:
                return sh
        raise Failure(f"the file has no '{name}' section")

    def segments(self, kind: int) -> list:
        return [p for p in self.phdrs if p["type"] == kind]

    def symbols(self) -> list:
        symtab = self.section(".symtab")
        strtab = self.shdrs[symtab["link"]]
        strings = self.raw[strtab["offset"]:strtab["offset"] + strtab["size"]]
        out = []
        for i in range(symtab["size"] // 24):
            name, info, other, shndx, value, size = struct.unpack_from(
                "<IBBHQQ", self.raw, symtab["offset"] + i * 24)
            out.append({"name": self._str(strings, name), "bind": info >> 4,
                        "type": info & 15, "other": other, "shndx": shndx,
                        "value": value, "size": size})
        return out


def check(condition, message: str):
    if not condition:
        raise Failure(message)


# ---------------------------------------------------------------------------
# The invariants, one function per group
# ---------------------------------------------------------------------------

def check_header(elf: Elf, path: str):
    check(elf.ident[:4] == b"\x7fELF", "the magic is not ELF's")
    check(elf.ident[4] == 2, f"e_ident says class {elf.ident[4]}, not 64-bit")
    check(elf.ident[5] == 1, f"e_ident says data {elf.ident[5]}, not "
                             f"little-endian")
    check(elf.ident[6] == 1, "e_ident's version is not 1")
    check(elf.ident[7:] == b"\0" * 9, "e_ident's padding is not zero")
    check(elf.e_type == 2, f"e_type is {elf.e_type}, not EXEC")
    check(elf.e_machine == 62, f"e_machine is {elf.e_machine}, not x86-64")
    check(elf.e_version == 1, "e_version is not 1")
    check(elf.e_ehsize == 64, f"e_ehsize is {elf.e_ehsize}, not 64")
    check(elf.e_phentsize == 56, f"e_phentsize is {elf.e_phentsize}, not 56")
    check(elf.e_shentsize == 64, f"e_shentsize is {elf.e_shentsize}, not 64")
    check(elf.e_phoff == 64, f"e_phoff is {elf.e_phoff}; the program headers "
                             f"follow the file header")
    check(elf.e_shstrndx == elf.e_shnum - 1,
          f"e_shstrndx is {elf.e_shstrndx} of {elf.e_shnum} sections; the "
          f"section names live in the last one")
    end = elf.e_shoff + elf.e_shnum * 64
    check(end <= len(elf.raw),
          f"the section headers run to {end}, past the file's {len(elf.raw)}")
    # The bug this one is here for wrote a file of no bytes at all and
    # reported success, because nothing it did had failed.
    check(len(elf.raw) > PAGE,
          f"'{os.path.basename(path)}' is {len(elf.raw)} bytes; a binary is "
          f"at least a page")


def check_segments(elf: Elf, stack_size: int):
    check(elf.e_phnum == 6, f"{elf.e_phnum} program headers, not 6")
    loads = elf.segments(PT_LOAD)
    check(len(loads) == 4, f"{len(loads)} PT_LOADs, not 4")

    headers, text, rodata, data = loads
    check(headers["offset"] == 0 and headers["vaddr"] == IMAGE_BASE,
          "the first PT_LOAD does not map the file's own headers")
    check(headers["flags"] == PF_R,
          f"the headers' segment is {flags_str(headers['flags'])}, not R; "
          f"a program that follows its own program headers has to read them")
    check(headers["filesz"] >= elf.e_phoff + elf.e_phnum * 56,
          "the headers' segment does not cover the program headers")
    check(text["flags"] == PF_R | PF_X,
          f"the text segment is {flags_str(text['flags'])}, not R E")
    check(rodata["flags"] == PF_R,
          f"the rodata segment is {flags_str(rodata['flags'])}, not R")
    check(data["flags"] == PF_R | PF_W,
          f"the data segment is {flags_str(data['flags'])}, not RW")

    for p in elf.phdrs:
        check(not (p["flags"] & PF_W and p["flags"] & PF_X),
              f"a segment is both writable and executable "
              f"({flags_str(p['flags'])})")
        check(p["offset"] + p["filesz"] <= len(elf.raw),
              "a segment's file range runs past the end of the file")
        if p["type"] == PT_LOAD:
            check(p["align"] == PAGE, f"a PT_LOAD aligns to {p['align']}, "
                                      f"not a page")

    check(text["vaddr"] <= elf.e_entry < text["vaddr"] + text["filesz"],
          f"the entry point {elf.e_entry:#x} is not inside the executable "
          f"segment")

    stack = elf.segments(PT_GNU_STACK)
    check(len(stack) == 1, "there is no PT_GNU_STACK; without one the kernel "
                           "falls back to an executable stack")
    check(not stack[0]["flags"] & PF_X,
          f"PT_GNU_STACK is {flags_str(stack[0]['flags'])}; the stack must "
          f"not be executable")
    check(stack[0]["flags"] == PF_R | PF_W,
          f"PT_GNU_STACK is {flags_str(stack[0]['flags'])}, not RW")
    check(stack[0]["memsz"] == stack_size,
          f"PT_GNU_STACK asks for {stack[0]['memsz']} bytes of stack, and "
          f"the compiler was told {stack_size}")

    relro = elf.segments(PT_GNU_RELRO)
    check(len(relro) == 1, "there is no PT_GNU_RELRO")
    check(relro[0]["flags"] == PF_R,
          f"PT_GNU_RELRO is {flags_str(relro[0]['flags'])}, not R")
    check(relro[0]["offset"] == data["offset"]
          and relro[0]["vaddr"] == data["vaddr"],
          "PT_GNU_RELRO does not begin where the writable segment does")
    check(relro[0]["memsz"] % PAGE == 0,
          f"PT_GNU_RELRO covers {relro[0]['memsz']} bytes, which is not a "
          f"whole number of pages; it is sealed a page at a time")
    check(relro[0]["memsz"] <= data["memsz"],
          "PT_GNU_RELRO reaches past the segment it seals")


def flags_str(f: int) -> str:
    return ("R" if f & PF_R else "") + ("W" if f & PF_W else "") \
        + ("E" if f & PF_X else "") or "none"


def check_sections(elf: Elf):
    want = ["", ".text", ".rodata", ".data", ".symtab", ".strtab",
            ".shstrtab"]
    got = [sh["sname"] for sh in elf.shdrs]
    check(got == want, f"the sections are {got}, not {want}")

    text, rodata, data = elf.shdrs[1], elf.shdrs[2], elf.shdrs[3]
    check(text["type"] == SHT_PROGBITS
          and text["flags"] == SHF_ALLOC | SHF_EXECINSTR,
          ".text is not allocated executable program bits")
    check(rodata["flags"] == SHF_ALLOC, ".rodata is not read-only allocated")
    check(data["flags"] == SHF_WRITE | SHF_ALLOC,
          ".data is not writable allocated")

    symtab, strtab = elf.shdrs[4], elf.shdrs[5]
    check(symtab["type"] == SHT_SYMTAB, ".symtab is not a symbol table")
    check(symtab["entsize"] == 24,
          f".symtab's entries are {symtab['entsize']} bytes, not 24")
    check(symtab["size"] % 24 == 0,
          f".symtab is {symtab['size']} bytes, which is not whole entries")
    check(symtab["link"] == 5,
          f".symtab's names are said to be in section {symtab['link']}, "
          f"not .strtab")
    check(strtab["type"] == SHT_STRTAB, ".strtab is not a string table")
    check(elf.shdrs[6]["type"] == SHT_STRTAB, ".shstrtab is not a string "
                                              "table")

    for sh in elf.shdrs[1:]:
        check(sh["offset"] + sh["size"] <= len(elf.raw),
              f"'{sh['sname']}' runs past the end of the file")
    loads = elf.segments(PT_LOAD)
    check(text["addr"] == loads[1]["vaddr"] and text["size"] == loads[1]["filesz"],
          ".text and the executable segment describe different runs of bytes")


def check_symbols(elf: Elf, exported: set, local: set, hashed: set):
    syms = elf.symbols()
    symtab = elf.section(".symtab")
    check(len(syms) >= 2, "the symbol table holds nothing")
    first = syms[0]
    check(first["name"] == "" and first["value"] == 0 and first["size"] == 0
          and first["shndx"] == 0,
          "the first symbol is not the absent one")

    # locals first, and the section header says where they stop: a
    # reader relies on it, so it has to be true of the table as written
    nlocal = symtab["info"]
    check(1 <= nlocal <= len(syms),
          f".symtab's sh_info is {nlocal}, outside the table's "
          f"{len(syms)} entries")
    for i, sym in enumerate(syms):
        want = STB_LOCAL if i < nlocal else STB_GLOBAL
        check(sym["bind"] == want,
              f"symbol {i} '{sym['name']}' is "
              f"{'local' if sym['bind'] == STB_LOCAL else 'global'}, and "
              f"sh_info says the globals start at {nlocal}")

    by_name = {s["name"]: s for s in syms if s["name"]}
    check("_start" in by_name, "there is no _start symbol")
    check(by_name["_start"]["value"] == elf.e_entry,
          "_start is not where the header says the program begins")

    for name in exported:
        check(name in by_name, f"'{name}' is not in the symbol table")
        check(by_name[name]["bind"] == STB_GLOBAL,
              f"'{name}' is @export and should be global, but it is local")
    for name in local:
        check(name in by_name, f"'{name}' is not in the symbol table")
        check(by_name[name]["bind"] == STB_LOCAL,
              f"'{name}' carries no @export and should be local, but it is "
              f"global")
    for stem in hashed:
        matches = [n for n in by_name if stem in n]
        check(matches, f"no symbol names '{stem}'")
        for n in matches:
            at = n.index(stem) + len(stem)
            digits = n[at:at + 16]
            check(len(digits) == 16
                  and all(c in "0123456789abcdef" for c in digits),
                  f"'{n}' does not carry a sixteen-digit definition hash "
                  f"after '{stem}'")

    text = elf.shdrs[1]
    funcs = [s for s in syms if s["type"] == STT_FUNC]
    check(funcs, "no function is named in the symbol table")
    for sym in funcs:
        check(sym["shndx"] == 1,
              f"'{sym['name']}' says it lives in section {sym['shndx']}, "
              f"not .text")
        check(sym["size"] > 0,
              f"'{sym['name']}' is {sym['size']} bytes long")
        check(text["addr"] <= sym["value"]
              and sym["value"] + sym["size"] <= text["addr"] + text["size"],
              f"'{sym['name']}' runs from {sym['value']:#x} for "
              f"{sym['size']} bytes, which is not inside .text")

    # No two functions may claim the same byte.  This is the check that
    # a size taken as the distance to the wrong neighbour cannot pass:
    # a run backwards becomes a huge unsigned length, and a run to the
    # far side of the text swallows everything between.
    ordered = sorted(funcs, key=lambda s: s["value"])
    for a, b in zip(ordered, ordered[1:]):
        check(a["value"] + a["size"] <= b["value"],
              f"'{a['name']}' runs from {a['value']:#x} for {a['size']} "
              f"bytes and so reaches into '{b['name']}' at {b['value']:#x}")
    covered = sum(s["size"] for s in funcs)
    check(covered <= text["size"],
          f"the functions claim {covered} bytes of a .text that is "
          f"{text['size']}")


def check_trimming(elf: Elf, present: set, absent: set):
    names = {s["name"] for s in elf.symbols()}
    for name in present:
        check(name in names,
              f"'{name}' is reached by this program but is not in the binary")
    for name in absent:
        check(name not in names,
              f"'{name}' cannot be reached by this program and should have "
              f"been left out")


def check_readelf(path: str) -> str:
    """A second reader's opinion, where one is installed."""
    exe = shutil.which("readelf")
    if exe is None:
        return "readelf is not installed; the file was parsed here only"
    run = subprocess.run([exe, "-a", path], capture_output=True)
    check(run.returncode == 0,
          f"readelf refused the file (status {run.returncode})")
    text = run.stdout.decode("utf-8", "replace") \
        + run.stderr.decode("utf-8", "replace")
    for line in text.splitlines():
        low = line.lower()
        check("error" not in low and "warning" not in low
              and "corrupt" not in low and "unable to" not in low,
              f"readelf says: {line.strip()}")
    return ""


# ---------------------------------------------------------------------------
# Driving the compiler
# ---------------------------------------------------------------------------

def compile_probe(compiler, source: str, out: str, extra=()) -> None:
    cmd = compiler + [source, "-o", out] + list(extra)
    run = subprocess.run(cmd, capture_output=True, cwd=topdir)
    if run.returncode != 0:
        raise Failure(
            f"ngplc refused '{os.path.basename(source)}': "
            + run.stdout.decode("utf-8", "replace").strip().splitlines()[0]
            if run.stdout.strip() else f"ngplc failed with {run.returncode}")


def refuse(compiler, source: str, out: str, extra) -> str:
    """Run the compiler expecting it to say no, and answer what it said."""
    cmd = compiler + [source, "-o", out] + list(extra)
    run = subprocess.run(cmd, capture_output=True, cwd=topdir)
    check(run.returncode != 0,
          f"ngplc accepted {' '.join(extra)}, which it should refuse")
    return run.stdout.decode("utf-8", "replace").strip()


def main() -> int:
    compiler = ["python", "-m", "interp", "src/ngplc.ngpl", "--"]
    for arg in sys.argv[1:]:
        if arg == "--compiler=native":
            compiler = [os.path.join(topdir, "build", "ngplc")]
        elif arg == "--compiler=interp":
            pass
        else:
            print(f"unknown option '{arg}'", file=sys.stderr)
            return 2

    probes = os.path.join(topdir, "tests", "compile", "elf")
    work = tempfile.mkdtemp(prefix="ngpl-elf-")
    passed = failed = 0
    notes = []

    def case(name, fn):
        nonlocal passed, failed
        try:
            note = fn()
        except Failure as e:
            print(f"FAIL {name}: {e}")
            failed += 1
        else:
            if note:
                notes.append(note)
            print(f"ok   {name}")
            passed += 1

    sym_src = os.path.join(probes, "probe_symbols.ngpl")
    sym_bin = os.path.join(work, "probe_symbols")
    wv_src = os.path.join(probes, "probe_writev.ngpl")
    wv_bin = os.path.join(work, "probe_writev")

    try:
        compile_probe(compiler, sym_src, sym_bin)
        compile_probe(compiler, wv_src, wv_bin)
    except Failure as e:
        print(f"FAIL building the probes: {e}")
        return 1

    sym = Elf(open(sym_bin, "rb").read())
    wv = Elf(open(wv_bin, "rb").read())

    case("elf header", lambda: check_header(sym, sym_bin))
    case("segments and their permissions",
         lambda: check_segments(sym, 8 * 1024 * 1024))
    case("sections", lambda: check_sections(sym))
    case("symbol table",
         lambda: check_symbols(
             sym,
             exported={"shared(i64, i64) → i64"},
             local={"main() → ∅", "_start"},
             hashed={"Point#"}))
    case("an unreachable runtime routine is left out",
         lambda: check_trimming(
             sym,
             present={"RT_PRINTI", "RT_ABORT", "RT_ALLOC"},
             absent={"RT_WRITEV", "RT_TORAW", "RT_FWRITE", "RT_FREAD",
                     "RT_DENTS"}))
    case("a reached runtime routine is kept",
         lambda: check_trimming(
             wv,
             present={"RT_WRITEV", "RT_TORAW", "RT_ALLOC"},
             absent={"RT_DENTS"}))
    case("the writing probe is well formed too",
         lambda: (check_header(wv, wv_bin),
                  check_segments(wv, 8 * 1024 * 1024),
                  check_sections(wv), None)[-1])
    case("readelf reads it", lambda: check_readelf(sym_bin))

    def stack_option():
        out = os.path.join(work, "probe_stack")
        compile_probe(compiler, sym_src, out, ["--stack-size=16M"])
        check_segments(Elf(open(out, "rb").read()), 16 * 1024 * 1024)

    def guard_option():
        out = os.path.join(work, "probe_guard")
        compile_probe(compiler, sym_src, out,
                      ["--guard-size=128K", "--stack-size=4M"])
        check_segments(Elf(open(out, "rb").read()), 4 * 1024 * 1024)

    def bad_options():
        out = os.path.join(work, "probe_bad")
        said = refuse(compiler, sym_src, out, ["--stack-size=banana"])
        check("wants a size" in said, f"the complaint was: {said}")
        said = refuse(compiler, sym_src, out, ["--stack-size=8"])
        check("one page" in said, f"the complaint was: {said}")
        said = refuse(compiler, sym_src, out, ["--guard-size=2G"])
        check("gibibyte" in said, f"the complaint was: {said}")

    case("--stack-size reaches PT_GNU_STACK", stack_option)
    case("--guard-size is taken", guard_option)
    case("a size that is not one is refused", bad_options)

    for note in notes:
        print(f"note: {note}")
    print(f"\nelf invariants: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
