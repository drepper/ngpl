# ngplc Attempt 1 — What Stands, What Fell Short, What Attempt 2 Needs

Written per step 5 of the process in `CLAUDE.md`, after the first
implementation round.  `DESIGN.md` beside this file says what was
built; this file says what it proved and where it stops.

## What Stands

The whole pipeline exists and holds together: NGPL source → lexer →
parser → checker → IR → x86-64 → static ELF executable, written in
bootstrap NGPL (`ngplc.ngpl`, ~2900 lines), run by the Python
interpreter, emitting binaries that use only Linux syscalls.  The
conformance suite in `tests/compile/` runs every program through both
the interpreter and the compiled binary and diffs; seven programs
covering arithmetic (checked overflow, `@wrap`, division defaults,
shifts, rotate-free bit ops, `⌈ ⌊`), control flow (both range
directions, steps, `break`/`continue`, nesting), functions (recursion,
truthiness, conditional expressions), contracts (`@pre`/`@post`
enforced at runtime), and the abort paths (violation and overflow stop
the program with SIGABRT, as the interpreter's enforce semantic stops)
all agree with the interpreter.  Compiling a test file takes ~5–15 s
under the tree-walking interpreter — tolerable for now, far from the
edit-eval-check brief.

The data-oriented core proved out: tokens and AST are parallel flat
arrays with ids instead of references, per-function checking/lowering/
emission touch nothing mutable outside their function, and the ELF
layout is the only ordered step.  That is the shape the parallel
compiler needs, run serially because the bootstrap has no concurrency.

## What Fell Short

1. **core-0 is small.**  One integer width (i64), bool, and string
   literals.  No arrays, no strings as values, no structs, enums,
   optionals, units, floats, no globals, no `match`, no lambdas.  The
   compiler cannot begin to compile itself: self-hosting needs at
   least arrays, strings, structs, optionals, and hashes — the things
   `ngplc.ngpl` is made of.  That is the whole of attempt 2's frontier,
   and it drags in memory management (an allocator over `mmap`, arrays
   that grow) and a real runtime layer.
2. **No optimization at all.**  Every value lives in a stack slot;
   `x + 1` is two loads and a store.  Fine for correctness-first, but
   the "fast enough for an edit-eval-check loop" brief eventually wants
   register allocation, and the IR was shaped so one can be inserted
   between lower and emit without disturbing either.
3. **Diagnostics stop at the first parse error** (the checker collects
   many; the parser does not recover).  Diagnostic text quality is
   below the interpreter's (no source excerpt with a caret yet).
   `--diag=json` exists but the machine-readable story for
   *decisions* (optimization, layout) has not begun.
4. **The reserved-word sets disagree.**  The bootstrap parser reserves
   words ngplc does not (`start`, `impure`, `flag`, …), so ngplc
   accepts identifiers the bootstrap refuses — a subset violation in
   the accepting direction.  Attempt 2 should refuse exactly the
   bootstrap's keyword list.
5. **Column positions are byte-based** in ngplc but character-based in
   the interpreter; diagnostics on lines holding multi-byte glyphs
   point one or two cells off.
6. **`@post` limitations**: every `@post` on a function must name the
   result identically (the checker declares only the first name), and
   `@post` on a unit function is refused rather than supporting the
   condition-only form the full language shows (`@post(true)`).
7. **Contract semantics are enforce-only.**  `--contracts=` is not yet
   accepted by ngplc at all; the TODO's build-level choice (ignore/
   observe/enforce/quick-enforce) needs the driver flag and, for
   observe, an error stream the runtime can write to without stopping.
8. **`std.exit` inside an expression position** is typed `∅` but not
   modelled as noreturn in the checker's path analysis except as a
   statement; `f() if c else …` with an exiting side is refused
   conservatively.

## Bugs Found in the Bootstrap Along the Way

Fixed in this round (each with tests):

- `and`/`or` evaluated both sides; the spec says they short-circuit
  (`tests/test_short_circuit.ngpl`).
- A caller's frozen name (foreach/while/borrow) leaked into callees,
  refusing the callee's own use of the spelling
  (`tests/test_callee_scope.ngpl`).
- `open_file` passed `O_NOATIME` (0o1000000) believing it was
  `O_CLOEXEC` (0o2000000); reading a file the user does not own failed
  with EPERM.
- No NGPL program could write a file.  Added `dir.create_file`,
  `dir.create_dir`, `dir.open_dir`, `file.write`, `file.chmod`
  (`tests/test_file_write.ngpl`).
- The interpreter capped NGPL recursion at ~120 frames (Python's
  default limit across ~8 Python frames per NGPL call); raised in the
  interpreter's main.
- The unused-`mut` analysis did not count a method call as a possible
  modification, so `&mut` struct parameters mutated only through
  methods drew false warnings.

Known but not fixed (for the bootstrap list):

- A function returning the wrong runtime kind can escape the return
  check: a call with too few arguments curries even when the declared
  return type is `i64`, so the resulting lambda flows into an `i64`
  binding unrefused.  This cost an hour of debugging (`mknode` called
  with four of its five arguments) and would bite again; arity of a
  call whose result feeds a non-function type should be checked.
- `std.args.get(i)` raises on out-of-range instead of answering `∅`.
- Method calls on array literals (`[1i64].iterate()`) do not parse.
- Units cannot be written on struct fields, so ngplc stores plain
  integers and re-attaches `¤ptrdiff`/`¤byte` at use sites via
  `× 1¤unit` — noise the full language would not need.
- `std.print`/`println` reach only fd 1; diagnostics belong on stderr
  (`std.eprintln`, or a writable stderr handle).
- One source file per run; the multi-file compiler wants either
  `import` or several files parsed into one program, and the
  diagnostics machinery assumes a single source text throughout.

## Spec Work Owed

`spec/spec.md` does not yet describe the new std surface
(`create_file`, `create_dir`, `open_dir`, `write`, `chmod`).  The file
carries unrelated uncommitted edits in the working tree, so the
addition is deferred rather than mixed in; it should follow with the
next spec pass.

## The Plan for Attempt 2 (sketch)

1. Grow core-0 toward self-hosting in this order: sized integer family
   (u8…u64 with masking/extension), `str` values and building,
   dynamic arrays (mmap-backed allocator in the runtime, growth by
   doubling), structs by value, global `let`, optionals + `match`,
   hashes.  Each step extends the conformance suite first.
2. Refuse exactly the bootstrap's keyword set; track character columns.
3. Parser error recovery (synchronize at statement starts) so several
   parse errors report at once; source excerpt + caret in diagnostics.
4. A first register allocator (linear scan over the existing IR).
5. `--contracts=` in the driver, with observe writing to stderr.
6. Start the machine-readable decision log (`--log=json` on stdout
   beside the binary) so the tooling story begins with real content.
