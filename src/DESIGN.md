# ngplc — Attempt 1 of the Self-Hosted Compiler

This is the design record for the first attempt at the NGPL compiler,
written in the bootstrap subset of NGPL and run by the Python
interpreter in `interp/`.  Per the process in `CLAUDE.md`, an attempt is
expected to fall short; the analysis of where this one fell short lives
in `ANALYSIS.md` beside it and feeds the plan for attempt 2.

## What This Attempt Compiles

The compiler translates **core-0**, a strict subset of NGPL, to static
x86-64 Linux ELF executables that use only the kernel's syscall
interface (no libc).  A core-0 program means exactly what the bootstrap
interpreter says it means; anything outside core-0 is refused by name,
never misread — the same rule the bootstrap holds to against the full
language.

core-0 holds:

- types: `i64`, `bool`, plus `str` literals where `std.println` and
  `assert` take them.  One width keeps sign-extension and masking out
  of the first backend; more widths are attempt-2 work.
- functions: `fn name(a : i64, …) → i64:` (≤ 6 parameters), `@start`,
  `@impure`, `@pre(cond)`, `@post(r: cond)`, `@noreturn`; bodies with
  early `return` and the trailing expression as the value.
- statements: `let x : i64 = e`, `let x : mut i64 = e`, `x ← e`,
  `_ ← e`, `if`/`elif`/`else`, `while`, `foreach i := a…b` and
  `a…s…b`, `break`/`continue`, `return`, expression statements.
- expressions: integer literals (decimal, hex, `⁻` prefix), `true`/
  `false`, variables, calls, `+ - × ⌈ ⌊`, `« » & | ^ ~`, comparisons
  `= ≠ < > <= >=`, `and or not ∧ ∨ ¬`, `a if c else b`, `@wrap(…)`,
  and `(a ÷ b) ?? d` / `(a % b) ?? d` — the coalesced form is the only
  one core-0 admits, because `÷` answers a result and core-0 has no
  general result type to hand one on with.
- builtins: `std.println(fmt, …)` / `std.print` with `{}` fields over
  i64, bool and str arguments; `std.exit(code)`; `assert(cond)`,
  `assert_eq(a, b)`.

The compiled semantics follow the interpreter: signed overflow of
`+ - × ⁻` aborts (SIGABRT via `kill`, so the shell sees 134) unless
inside `@wrap`; a shift count ≥ 64 aborts; `÷`/`%` answer the default
when the divisor is 0 or the quotient overflows; `@pre`/`@post` are
evaluated on entry/exit and a violation reports and aborts (the
`enforce` semantic; the driver accepts `--contracts=` and refuses the
other semantics for now rather than miscompiling them).

## Pipeline and Data Flow

Every stage is a function from immutable inputs to a fresh value; the
only mutation is inside builders (append-only arrays under
construction).  There is no global mutable state.

    bytes ──lex──▶ Toks ──parse──▶ Ast ──check──▶ types/symbols
                                     │
                                     ├──lower──▶ Ir (per function)
                                     └──emit───▶ code bytes ──elf──▶ file

- **lex** (`byte[] → Toks`): iterative scan over the raw UTF-8 bytes.
  The multi-byte glyphs the language uses (`× ÷ ← → ⁻ … ∅ ¨ ⌿` …) are
  matched as byte sequences from a fixed table, so no general UTF-8
  decoding is needed; identifiers are ASCII in core-0.  `Toks` is a
  structure of parallel arrays — kind, byte offset, length, line,
  column — rather than an array of token objects, which is both the
  array-programming style the project asks for and the layout a native
  build will want.
- **parse** (`Toks → Ast`): recursive descent for statements, Pratt
  (precedence climbing) for expressions, so recursion depth follows the
  program's actual nesting and not the number of precedence levels.
  `Ast` is flat: parallel arrays `kind/tok/lhs/rhs` indexed by node id,
  with an `extra` array for the variable-length pieces (argument lists,
  block statement lists).  A function definition is a row in a
  parallel set of `fns_*` arrays pointing at its body.  Flat ids
  instead of references sidestep deep tree recursion in every later
  pass and make the eventual data-parallel compile a matter of
  splitting id ranges.
- **check**: per function — a scope-stacked symbol table (arrays, no
  hash needed at these sizes), type of every expression node
  (`i64`/`bool`/`str`/`unit`), mutability and definite-initialization,
  arity and unknown-name errors, unused expression values (an error,
  as the interpreter has it), `break`/`continue` placement, purity
  (`std.println` and `@impure` callees demand an `@impure` caller),
  `@start` uniqueness, contract conditions being pure and boolean.
  Diagnostics carry file/line/column and are collected, not thrown;
  the driver renders them all and exits non-zero.
- **lower** (`Ast → Ir`): a linear three-address IR per function, flat
  arrays again: `op/a/b/dst` over virtual registers, `LABEL`/`BR`/
  `CBR` for control flow.  Contracts are lowered as ordinary condition
  code wrapped around the body.  The IR exists so the checker's output
  rather than raw syntax feeds the backend, and so attempt 2 can put
  optimizations between lower and emit without touching either.
- **emit** (`Ir → bytes`): x86-64.  Virtual registers live in stack
  slots off `rbp`; operands travel through `rax`/`rcx`.  Naive but
  correct; register allocation is deliberately attempt-2+.  Arithmetic
  emits `jo` to the abort stub unless the node was under `@wrap`.
  Calls use rdi/rsi/rdx/rcx/r8/r9, return in rax.  Jumps and calls are
  backpatched; string literals are interned into one rodata blob.
- **elf**: a static ELF64 executable, image base 0x400000, two PT_LOAD
  segments — text R+X, rodata R — entry `_start`, which calls the
  `@start` function and exits 0.  The runtime is a few emitted
  routines: `sys_write`, decimal i64 printing, `true`/`false`, and the
  abort path (message to fd 2, then `kill(getpid(), SIGABRT)`), all
  over raw syscalls.

Output goes under `build/` in the current directory (created if
missing), per the TODO's build-directory rule: `ngplc foo.ngpl` writes
`build/foo`; `-o path` overrides.

## Diagnostics, Human and Machine

Every diagnostic is a record (file, line, col, severity, message).
Human rendering is `file:line:col: error: message` with the source line
and a caret.  `--diag=json` renders each as one JSON object per line
instead, for the program-driven edit-eval-check loop the brief asks
for.  The same records feed both, so the two can never disagree.

## Parallelism

The bootstrap interpreter is sequential and offers no concurrency
primitive, so this attempt runs serially.  The design keeps the future
parallel shape anyway: after parsing, every function is checked,
lowered, and emitted independently of every other (symbol resolution
reads only the immutable top-level tables), so stage-2 can fan those
per-function passes out across cores without redesign.  Only layout
and the ELF write are inherently ordered.

## Conformance Testing

`tests/compile/` holds core-0 programs.  Each is run twice — by the
bootstrap interpreter, and compiled by ngplc and executed — and the
two outputs must match; `tests/compile/run_compile_tests.sh` drives
both and diffs.  The interpreter is the semantic authority, so this is
the subset rule made executable.

## Bootstrap Changes This Attempt Needed

Made (in `interp/`, each spec-consistent):

1. `and`/`or` now short-circuit in the evaluator, as the spec's table
   says; they evaluated both sides before.
2. File output: `dir.create_file(name, mode?)`, `dir.create_dir(name,
   mode?)`, `dir.open_dir(name)`, `file.write(bytes|str)`,
   `file.chmod(mode)` — a compiler must write an executable, and no
   write path existed.  `create_file` applies the stated mode despite
   the umask, so 0o755 means what it says.
3. `open_file`'s default flags mislabelled `O_NOATIME` (0o1000000) as
   `O_CLOEXEC` (0o2000000); reading a file the user does not own
   failed with EPERM.  Fixed.
4. `sys.setrecursionlimit` raised in the interpreter's main: the
   default capped NGPL programs at ~120 frames of their own, too few
   for a recursive-descent parser over ordinary nesting.

Proposed but not done (for the next bootstrap round):

- units on struct fields (`off : i64 ¤ptrdiff`) — the parser refuses
  them, so token/AST records store plain integers and re-attach units
  at use sites, which is noise the full language would not need.
- an error stream: `std.print` reaches only fd 1, so diagnostics go to
  stdout; `std.eprintln` (or `std.fs.stderr()`) would fix that.
- multiple source files per run (the diagnostics machinery assumes one
  source text end-to-end), so the compiler could be split into
  modules; today it is one file by necessity.
- `≤`/`≥` are not lexed although `≠` is; the ASCII `<=`/`>=` work.
