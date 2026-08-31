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

import json
import os
import re
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
    check(elf.e_phnum == 7, f"{elf.e_phnum} program headers, not 7")
    loads = elf.segments(PT_LOAD)
    check(len(loads) == 5, f"{len(loads)} PT_LOADs, not 5")

    # the bill's own segment comes last of what is loaded, so nothing
    # writable ever sits above something read only
    headers, text, rodata, data, bill = loads
    check(bill["flags"] == PF_R,
          f"the bill's segment is {flags_str(bill['flags'])}, not R")
    check(bill["offset"] > data["offset"],
          "the bill is loaded before the writable segment, not after it")
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
    want = ["", ".text", ".rodata", ".data", ".sbom", ".sbomstr", ".symtab",
            ".strtab", ".shstrtab"]
    got = [sh["sname"] for sh in elf.shdrs]
    check(got == want, f"the sections are {got}, not {want}")

    text, rodata, data = elf.shdrs[1], elf.shdrs[2], elf.shdrs[3]
    check(text["type"] == SHT_PROGBITS
          and text["flags"] == SHF_ALLOC | SHF_EXECINSTR,
          ".text is not allocated executable program bits")
    check(rodata["flags"] == SHF_ALLOC, ".rodata is not read-only allocated")
    check(data["flags"] == SHF_WRITE | SHF_ALLOC,
          ".data is not writable allocated")

    sbom, sbomstr = elf.shdrs[4], elf.shdrs[5]
    check(sbom["type"] == SHT_PROGBITS, ".sbom is not program bits")
    check(sbom["entsize"] == 12,
          f".sbom's rows are {sbom['entsize']} bytes, not 12")
    check(sbom["size"] % 12 == 0,
          f".sbom is {sbom['size']} bytes, which is not whole rows")
    check(sbomstr["type"] == SHT_STRTAB, ".sbomstr is not a string table")
    for sh in (sbom, sbomstr):
        check(sh["flags"] == SHF_ALLOC,
              f"{sh['sname']} is not read-only allocated; a program has to "
              f"be able to read its own bill, and never to write it")

    symtab, strtab = elf.shdrs[6], elf.shdrs[7]
    check(symtab["type"] == SHT_SYMTAB, ".symtab is not a symbol table")
    check(symtab["entsize"] == 24,
          f".symtab's entries are {symtab['entsize']} bytes, not 24")
    check(symtab["size"] % 24 == 0,
          f".symtab is {symtab['size']} bytes, which is not whole entries")
    check(symtab["link"] == 7,
          f".symtab's names are said to be in section {symtab['link']}, "
          f"not .strtab")
    check(strtab["type"] == SHT_STRTAB, ".strtab is not a string table")
    check(elf.shdrs[8]["type"] == SHT_STRTAB, ".shstrtab is not a string "
                                              "table")

    for sh in elf.shdrs[1:]:
        check(sh["offset"] + sh["size"] <= len(elf.raw),
              f"'{sh['sname']}' runs past the end of the file")
    loads = elf.segments(PT_LOAD)
    check(text["addr"] == loads[1]["vaddr"] and text["size"] == loads[1]["filesz"],
          ".text and the executable segment describe different runs of bytes")


SBOM_COMPILER, SBOM_SOURCE, SBOM_SOURCES, SBOM_OUTPUT = 0, 1, 2, 3
SBOM_FUNCTION = 4
SBOM_KIND = {SBOM_COMPILER: "compiler", SBOM_SOURCE: "source",
             SBOM_SOURCES: "sources", SBOM_OUTPUT: "output",
             SBOM_FUNCTION: "function"}


def sbom_rows(elf: Elf) -> list:
    """The bill, as (kind, name, digest) in the order it was written."""
    table, strs = elf.section(".sbom"), elf.section(".sbomstr")
    blob = elf.raw[strs["offset"]:strs["offset"] + strs["size"]]
    check(table["size"] % 12 == 0,
          f".sbom is {table['size']} bytes, which is not whole 12-byte rows")

    def txt(at):
        check(at < len(blob), f"a row points {at} bytes into a "
                              f"{len(blob)}-byte .sbomstr")
        return Elf._str(blob, at)

    out = []
    for i in range(table["size"] // 12):
        kind, name, digest = struct.unpack_from(
            "<III", elf.raw, table["offset"] + i * 12)
        check(kind in SBOM_KIND, f"row {i} says kind {kind}, which is none "
                                 f"of the ones a bill has")
        out.append((SBOM_KIND[kind], txt(name), txt(digest)))
    return out


def check_sbom(elf: Elf, sources: list):
    """Every binary says what it was made of, and there is no flag for it."""
    rows = sbom_rows(elf)
    kinds = [r[0] for r in rows]
    nfn = kinds.count("function")
    want = (["compiler"] + ["source"] * len(sources) + ["sources"]
            + ["function"] * nfn + ["output"])
    check(kinds == want, f"the bill's rows are {kinds}, not {want}")
    check(nfn > 0, "the bill names no function; a bill that cannot say "
                   "which function differs is only worth comparing")

    check(rows[0][1] != "", "the compiler row names no compiler")
    named = [r[1] for r in rows if r[0] == "source"]
    check(named == sources,
          f"the bill names {named} as the sources, not {sources}")
    # every function row names one, and no two name the same
    fnames = [r[1] for r in rows if r[0] == "function"]
    check(all(n != "" for n in fnames), "a function row names no function")
    check(len(set(fnames)) == len(fnames),
          f"two function rows name the same function: {fnames}")
    # the summary rows are about the whole thing and name nothing
    summaries = [r for r in rows if r[0] in ("sources", "output")]
    check(all(r[1] == "" for r in summaries),
          "a summary row carries a name; the program and its sources "
          "together are not named, only digested")

    for kind, name, digest in rows:
        check(len(digest) == 64,
              f"the {kind} row's digest is {len(digest)} characters, not 64")
        check(all(c in "0123456789abcdef" for c in digest),
              f"the {kind} row's digest is not lowercase hex: {digest!r}")

    # one source, so its digest and the digest of all the sources are the
    # same message hashed twice -- and had better come out the same
    if len(sources) == 1:
        one = next(r[2] for r in rows if r[0] == "source")
        allof = next(r[2] for r in rows if r[0] == "sources")
        check(one == allof,
              "with one source, that source's digest and the digest of all "
              f"the sources disagree: {one} and {allof}")

    # the bill is loaded, so a program can read it without opening a file
    sbom = elf.section(".sbom")
    inside = [p for p in elf.segments(PT_LOAD)
              if p["offset"] <= sbom["offset"]
              and sbom["offset"] + sbom["size"] <= p["offset"] + p["filesz"]]
    check(inside, ".sbom is in no loaded segment")
    check(inside[0]["flags"] == PF_R,
          f"the bill's segment is {flags_str(inside[0]['flags'])}, not r--")
    return f"the bill has {len(rows)} rows"


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


def check_sbom_tool(elf: "Elf", path: str) -> str:
    """The reader written in NGPL agrees with the one written here.

    tools/sbom walks the file with nothing but the file, which is the
    point of writing the bill into it; this holds that reader to the
    same rows this one finds.  A tool that is not built is a note
    rather than a failure: it is not part of the bootstrap.
    """
    tool = os.path.join("build", "sbom")
    if not os.path.exists(tool):
        return ("tools/sbom is not built, so the bill was read here only "
                "(ngplc tools/sbom.ngpl -o build/sbom)")
    run = subprocess.run([tool, path], capture_output=True)
    check(run.returncode == 0,
          f"tools/sbom refused the file (status {run.returncode}): "
          f"{run.stderr.decode('utf-8', 'replace').strip()}")
    lines = run.stdout.decode("utf-8", "replace").rstrip("\n").split("\n")
    mine = sbom_rows(elf)
    check(lines[0] == f"{path}: {len(mine)} rows",
          f"tools/sbom says {lines[0]!r}, not {len(mine)} rows")
    # the two kinds whose name is empty say what they are instead
    named = {"output": path,
             "sources": "(all sources, in the order they were read)"}
    said = []
    for line in lines[1:]:
        m = re.match(r"^  ([0-9a-f]+)  (\S+) *(.*)$", line)
        check(m is not None, f"tools/sbom wrote a row this cannot read: {line!r}")
        said.append((m.group(2), m.group(3), m.group(1)))
    want = [(k, n or named.get(k, ""), d) for k, n, d in mine]
    check(said == want, "tools/sbom and this reader disagree: "
          f"{[r for r in zip(want, said) if r[0] != r[1]][:1]}")
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


def compiler_sources() -> list:
    """The one file the compiler is rooted in, as build/sources.sh names it.

    Read rather than repeated: the rest of the program is reached from
    it by the @import lines the sources carry, so this is the only name
    anything outside the sources has to know.
    """
    text = open(os.path.join(topdir, "build", "sources.sh")).read()
    root = text.split("NGPLC_ROOT=", 1)[1].split("\n", 1)[0].strip()
    return [root]


# ---------------------------------------------------------------------------
# Compiling only what changed
# ---------------------------------------------------------------------------

INCR_PROBE = """\
fn answer() \u2192 i64:
    41

fn shown() \u2192 i64:
    answer() + 1

@start
@impure
fn main() \u2192 u8:
    std.println("{}", shown())
    0
"""


def incr_build(compiler, source: str, out: str, target: str = "") -> tuple:
    """Build with --incremental and answer (what it decided, the log)."""
    cmd = compiler + [source, "-o", out, "--incremental", "--log=json"]
    if target:
        cmd.append("--target=" + target)
    run = subprocess.run(cmd, capture_output=True, cwd=topdir)
    said = run.stdout.decode("utf-8", "replace")
    check(run.returncode == 0,
          f"ngplc refused an incremental build (status {run.returncode}): "
          f"{said.strip().splitlines()[:1]}")
    decisions = [line for line in said.splitlines()
                 if '"decision": "incremental' in line]
    check(len(decisions) == 1,
          f"--incremental said {len(decisions)} things about what it decided")
    return json.loads(decisions[0]), said


def incr_run(path: str) -> str:
    """What the program prints, which is what the mode must not change."""
    run = subprocess.run([path], capture_output=True)
    check(run.returncode == 0,
          f"the program built incrementally stopped with {run.returncode}")
    return run.stdout.decode("utf-8", "replace").strip()


def check_incremental(compiler, work: str) -> str:
    """A first build leaves room, and a later one writes only what moved.

    The whole of the mode is here: that a rebuild of an unchanged
    source reproduces the file byte for byte, that a change writes the
    functions that moved and copies the rest -- which the file shows,
    since only their bytes differ -- and that a function that outgrows
    the room it was given falls back to a whole build rather than
    writing something that does not fit.  Every build's program is run,
    because a layout that lines up and a program that answers wrongly
    is the failure this mode risks.
    """
    src = os.path.join(work, "incr_probe.ngpl")
    out = os.path.join(work, "incr_probe")
    open(src, "w").write(INCR_PROBE)
    if os.path.exists(out):
        os.remove(out)

    first, _ = incr_build(compiler, src, out)
    check(first["decision"] == "incremental-first",
          f"a build with no file to read said {first['decision']!r}")
    check(incr_run(out) == "42", "the first build answers wrongly")

    # every function of the program got room, and the room is trapped:
    # a jump into the gap between two functions stops rather than wanders
    elf = Elf(open(out, "rb").read())
    text = elf.section(".text")
    body = elf.raw[text["offset"]:text["offset"] + text["size"]]
    for sym in elf.symbols():
        if "\u2192" not in sym["name"]:
            continue
        end = sym["value"] - text["addr"] + sym["size"]
        check(body[end - 1] == 0xCC,
              f"the room after {sym['name']!r} is not trapped")

    was = open(out, "rb").read()
    again, _ = incr_build(compiler, src, out)
    check(again["decision"] == "incremental",
          f"a rebuild of an unchanged source said {again['decision']!r}")
    check(again["regenerated"] == 0,
          f"a rebuild of an unchanged source wrote {again['regenerated']} "
          "functions again")
    check(open(out, "rb").read() == was,
          "a rebuild of an unchanged source wrote a different file")

    # one function changed, and no more of the code than that may move
    open(src, "w").write(INCR_PROBE.replace("    41\n", "    42\n"))
    moved, _ = incr_build(compiler, src, out)
    check(moved["decision"] == "incremental",
          f"a change that fits its room said {moved['decision']!r}")
    check(moved["regenerated"] >= 1,
          "a change that fits its room wrote nothing again")
    check(incr_run(out) == "43", "the rebuilt program answers wrongly")
    now = open(out, "rb").read()
    lo, hi = text["offset"], text["offset"] + text["size"]
    differ = [i for i in range(lo, hi) if was[i] != now[i]]
    check(len(differ) <= 256,
          f"{len(differ)} bytes of the code changed for a one-line change")

    # One that cannot fit where it stands is written past everything
    # the last build used, in a section of its own -- loaded and
    # executable and not writable, like the .text it came out of.  No
    # jump is left behind at the old address: a function that names one
    # that moved is written again too, and calls it where it now is.
    grown = INCR_PROBE.replace(
        "    41\n",
        "    let a : i64 = 41\n"
        "    let b : i64 = a + 1\n"
        "    let c : i64 = b + 1\n"
        "    let d : i64 = c + 1\n"
        "    d - 3\n")
    open(src, "w").write(grown)
    moved2, _ = incr_build(compiler, src, out)
    check(moved2["decision"] == "incremental",
          f"a function that outgrew its room said {moved2['decision']!r}")
    check(incr_run(out) == "42", "the program with the moved function is wrong")
    elf2 = Elf(open(out, "rb").read())
    over = [sh for sh in elf2.shdrs
            if sh["sname"].startswith(".text") and sh["sname"] != ".text"]
    check(len(over) >= 1, "the function that moved got no section of its own")
    want = SHF_ALLOC | SHF_EXECINSTR
    for sh in over:
        check(sh["flags"] & want == want,
              f"{sh['sname']} is not loaded and executable")
        check(not sh["flags"] & SHF_WRITE, f"{sh['sname']} is writable")
        check(sh["addr"] >= elf2.section(".text")["addr"] + elf2.section(".text")["size"],
              f"{sh['sname']} overlaps .text")
    lo = min(sh["addr"] for sh in over)
    hi = max(sh["addr"] + sh["size"] for sh in over)
    covered = [p for p in elf2.segments(PT_LOAD)
               if p["vaddr"] <= lo and p["vaddr"] + p["filesz"] >= hi]
    check(covered, "no loaded segment covers the sections that were added")
    check(all(p["flags"] & PF_W == 0 for p in covered),
          "the segment holding the moved code is writable")
    where = {sy["name"]: sy["value"] for sy in elf2.symbols()}
    grew = [nm for nm in where if "answer" in nm]
    check(grew and where[grew[0]] >= lo,
          "the function that outgrew its room is not in the new section")

    # A function the previous build did not have has no slot at all,
    # and no room is the one thing that is still a whole build.
    open(src, "w").write(INCR_PROBE + """
fn fourth(n : i64) \u2192 i64:
    n + 4
""")
    fell, _ = incr_build(compiler, src, out)
    check(fell["decision"] == "incremental-fallback",
          f"a function the file did not have said {fell['decision']!r}")
    check(fell["why"], "the fallback did not say why")
    check(incr_run(out) == "42", "the program built after a fallback is wrong")

    # A change that grows the read-only data -- here the jump table of
    # a dense dispatch that was written again -- goes into the room the
    # first build reserved past .rodata's end, so .data does not move
    # and the rebuild still lines up.  Before the room was reserved
    # this fell back whenever the growth crossed a page.
    jt_src = os.path.join(work, "incr_dispatch.ngpl")
    jt_bin = os.path.join(work, "incr_dispatch")
    dispatch = open(os.path.join(topdir, "tests", "compile",
                                 "t11_dispatch.ngpl")).read()
    open(jt_src, "w").write(dispatch)
    if os.path.exists(jt_bin):
        os.remove(jt_bin)
    incr_build(compiler, jt_src, jt_bin)
    before = Elf(open(jt_bin, "rb").read())
    ro0 = before.section(".rodata")["size"]
    data0 = before.section(".data")["addr"]
    open(jt_src, "w").write(dispatch.replace("return 103", "return 203"))
    grew, _ = incr_build(compiler, jt_src, jt_bin)
    check(grew["decision"] == "incremental",
          f"a jump table that was written again said {grew['decision']!r}")
    after = Elf(open(jt_bin, "rb").read())
    check(after.section(".rodata")["size"] > ro0,
          "the jump table written again did not grow the read-only data")
    check(after.section(".data")["addr"] == data0,
          "the writable data moved, which every address in the old code names")
    check("dense 3 203" in incr_run(jt_bin),
          "the rebuilt dispatch answers wrongly")

    # The five targets that share the driver reach the same conclusion.
    # They are built and compared rather than run, which needs no
    # emulator: what a cross build gets wrong here is the layout, and
    # the layout is what a rebuild that lines up is claiming.  Both
    # classes, since the widths differ.
    open(src, "w").write(INCR_PROBE)
    for target in ("aarch64", "riscv32"):
        cross = os.path.join(work, "incr_probe_" + target)
        if os.path.exists(cross):
            os.remove(cross)
        one, _ = incr_build(compiler, src, cross, target)
        check(one["decision"] == "incremental-first",
              f"a first build for {target} said {one['decision']!r}")
        kept = open(cross, "rb").read()
        two, _ = incr_build(compiler, src, cross, target)
        check(two["decision"] == "incremental" and two["regenerated"] == 0,
              f"an unchanged rebuild for {target} said {two}")
        check(open(cross, "rb").read() == kept,
              f"an unchanged rebuild for {target} wrote a different file")
    return ""


def main() -> int:
    compiler = ["python", "-m", "interp"] + compiler_sources() + ["--"]
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

    def rel(p):
        # the bill records a source under the name the compiler was
        # given, which is the path these probes are compiled by
        return p

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
    def multi_bill():
        # A program from several files, named by one: the third imports
        # the second, which imports the first.  The bill names each one
        # in the order they were read -- which is the order the imports
        # put them in, each after what it is written against -- and
        # then all of them together.
        parts = [os.path.join("tests", "compile", "multi", "split", f)
                 for f in ("a.ngpl", "b.ngpl", "c.ngpl")]
        out = os.path.join(work, "probe_multi")
        compile_probe(compiler, parts[2], out)
        return check_sbom(Elf(open(out, "rb").read()), parts)

    case("every binary carries its bill of materials",
         lambda: check_sbom(sym, [rel(sym_src)]))
    case("a bill of imported sources keeps them in order", multi_bill)
    case("readelf reads it", lambda: check_readelf(sym_bin))
    case("the reader written in NGPL reads it too",
         lambda: check_sbom_tool(sym, sym_bin))

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
        for bad in ("-Ox", "-O-1", "-O2x"):
            said = refuse(compiler, sym_src, out, [bad])
            check("takes a level" in said, f"the complaint was: {said}")

    def optimization_level():
        """What -O asked for reaches the code generator, and says so.

        The level is what the phases that generate code read; nothing
        turns on it yet, so what is checked is that every form of the
        option arrives as the number it names and that a build without
        it is at zero.
        """
        out = os.path.join(work, "probe_opt")
        for extra, want in (([], 0), (["-O"], 1), (["-O1"], 1),
                            (["-O2"], 2), (["-O7"], 7)):
            cmd = compiler + [sym_src, "-o", out, "--log=json"] + extra
            run = subprocess.run(cmd, capture_output=True, cwd=topdir)
            check(run.returncode == 0,
                  f"ngplc refused {extra}: {run.returncode}")
            said = run.stdout.decode("utf-8", "replace")
            lines = [line for line in said.splitlines()
                     if '"decision": "optimize"' in line]
            check(len(lines) == 1,
                  f"{extra or 'no -O'} said {len(lines)} things about the level")
            check(json.loads(lines[0])["level"] == want,
                  f"{extra or 'no -O'} arrived as {lines[0]}")

    case("--incremental writes only what changed",
         lambda: check_incremental(compiler, work))
    case("-O reaches the code generator", optimization_level)
    case("--stack-size reaches PT_GNU_STACK", stack_option)
    case("--guard-size is taken", guard_option)
    case("a size that is not one is refused", bad_options)

    for note in notes:
        print(f"note: {note}")
    print(f"\nelf invariants: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
