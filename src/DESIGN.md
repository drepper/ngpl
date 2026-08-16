# ngplc — Attempts 2 and 3 of the Self-Hosted Compiler

The design record for the second attempt, written in the bootstrap
subset of NGPL and run by the Python interpreter.  Attempt 1 is
archived under `old/attempt1/` with its own DESIGN and ANALYSIS; this
attempt grows the compiled language from core-0 to **core-1** and
adopts the project's control-flow policy end to end.  What this
attempt proved and where it stops is in `ANALYSIS.md` beside it.

## What This Attempt Compiles

**core-1**, a strict subset of NGPL, to static x86-64 Linux ELF
executables using only the kernel's syscall interface.  A core-1
program means exactly what the bootstrap interpreter says it means;
anything outside is refused by name — including the bootstrap's
reserved words, which attempt 1 wrongly accepted as identifiers.

Over core-0, core-1 adds:

- **the sized integer family** `i8…i64`, `u8…u64`: untyped literals
  adopt the width of what they meet (with exact folding of literal
  arithmetic and range checks at adoption); mixed signedness is
  refused; same-signedness widths widen to the wider side.  Checked
  arithmetic aborts on leaving the range at every width, `@wrap` masks
  and re-extends, shifts wrap with the count held below the type's
  value bits, division truncates toward zero, ordering and division
  are signedness-aware, and u64 prints past the signed range.
- **units-lite**: `¤ptrdiff` and `¤byte` on integer bindings and
  parameters, carried through arithmetic per the spec's scalar rules;
  `#` answers a measured count (`¤byte` for `u8[]`, else `¤ptrdiff`)
  and a subscript must carry the array's measure, untyped literals
  exempt.
- **arrays** `T[]` of integer elements: born from a literal, grown by
  `push`, indexed with bounds checks, walked by `foreach`, handed
  around by `&`/`&mut` borrow (written `&name` at the call, as the
  bootstrap has it), with `pop()`/`get(i)` answering through `?? d`.
- **strings** as values: literals, variables, parameters, returns,
  `⧺`, content equality, `#s` counting characters (lead bytes), and
  printing.
- **globals**: constant-initialized scalars, immutable ones read
  anywhere, `mut` ones an effect behind `@impure`.
- **`std.implementation`**: `name`/`language`/`interpreter`/`compiled`
  folded to constants about ngplc itself, so one test suite serves
  every implementation.

Attempt 3 grows core-1 to **core-2** with structs:

- **structs** with fields of every core scalar kind plus strings and
  arrays; literals `Name{f: v, …}` checked complete; field reads and
  `x.f ← v` stores; `impl` blocks whose methods take `&self` or
  `&mut self` (a method is a function named `Name.m` with the receiver
  first) or no receiver at all (a static, asked of the struct's name).
  A struct value is a pointer to an allocated block of one slot per
  field.  The subset keeps ownership trivial: a struct binding is born
  from a literal or a call and rebound only to another fresh one,
  travels by `&`/`&mut` borrow, and is returned only freshly built —
  aliasing cannot arise, so value-versus-reference semantics cannot
  diverge from the bootstrap's move-and-borrow rules.  A struct may be
  declared below whatever names it (the parser pre-scans the token
  stream for struct names in one sweep).  `&mut self` methods and
  field stores demand a `mut` binding or `&mut` parameter, fields
  inheriting their holder's mutability.
- **optionals** `T?` of any scalar or struct, with `∃(v)`, `∅`,
  `match` over the two shapes (the bound name scoped to the present
  arm, a trailing match handing each arm's value on as the function's
  answer), presence as truthiness, comparison with `∅` (and only ∅ —
  content comparison waits), and `??` generalized to every optional.
  The representation makes absence free: an optional is a pointer,
  `∅` the null one and `∃(v)` a box holding the value, so a presence
  test is one compare against zero, `= ∅` needs no special lowering
  at all (∅ is the constant 0), and nested `∃(∅)` falls out naturally.
  `∃` allocates, so it is not speculatable; `∅` is.

## Pipeline and Data Flow

Unchanged in shape from attempt 1 — flat parallel arrays and ids
throughout, every post-parse pass per-function over immutable inputs,
serial today but shaped for the parallel compiler:

    bytes ──lex──▶ Toks ──parse──▶ Ast ──check──▶ types/slots
                                     ├──lower──▶ IrFn (per function)
                                     └──emit───▶ code ──layout──▶ ELF

Types are one integer each: `16 + sgn + 2·bits + 256·unit` for the
integer family, `4096 + elem` for arrays, `65536·refkind` added on
parameters.  The checker threads a `want` type downward so untyped
literals settle where the spec settles them, folds literal-only
subtrees exactly, and stamps every node with a type and every binding
and use with a frame slot.  The IR carries a width (`bits + 256·sgn`)
on every operation, which is all the backend needs to pick
instructions, condition codes, and checks.

## The Control-Flow Policy, Applied

CLAUDE.md's policy: decisions are data; an `if` that needs a jump is
the exception.  The research behind the choices here — cmov
profitability, if-conversion legality, switch lowering thresholds,
GPU divergence — is summarized with sources at the end.

**In the compiler's own source.**  The lexer classifies every byte
through a 256-entry class table; single-byte tokens are the table
entry itself.  Multi-byte glyphs resolve by one hash probe over their
packed UTF-8 bytes, keywords by one probe of the keyword hash — no
comparison ladders.  Columns are characters, counted by the
lead-byte test `(b & 0xC0) ≠ 0x80`.

**In the generated code.**

- Comparisons materialize with `setcc`; truth values are 0/1 and
  combine with `and`/`or`/`xor`.
- `⌈` and `⌊` are `cmp` + `cmovcc`, signedness-aware, always — their
  operands are evaluated regardless, so nothing is speculated.
- `a if c else b` becomes a `cmov` select when both sides are **safe
  to speculate**: no effects and no faults.  The legality rule follows
  what real compilers use: variables, constants, `@wrap` arithmetic,
  bitwise ops, comparisons and selects of such pass; checked
  arithmetic (may abort), array indexing (bounds abort), and calls do
  not.  Otherwise the conditional stays branched.
- `and`/`or` with a speculatable right side are evaluated eagerly —
  three straight-line instructions instead of a branch; the
  short-circuit form remains only where the right side could be
  observed (effects or faults).
- A dense ladder whose every arm **returns a constant** (default
  included) is not control flow at all: it folds to a **value table**
  — index clamp by `cmov`, one load from a table of data in rodata,
  one `cmov` against the default — zero branches, GCC's
  switch-conversion made policy.  Verified in the binary: the folded
  function carries no indirect jump and two cmovs.
- A dense if/elif ladder testing one variable against integer
  constants (whose arms are real code) lowers to a **jump table**: bounds check (`sub`; unsigned
  `cmp`+`jae`, one never-taken branch to the default), then one
  indirect `jmp [table + idx*8]` through a table of code addresses in
  rodata.  Profitability follows the window real compilers use: at
  least 4 cases and span ≤ 3× the case count (LLVM asks ≥4 and ≥10%
  density; GCC's -O2 ratio is 8); sparse ladders stay ladders, which
  the research says is right — an indirect jump predicted worse than a
  short predictable ladder is not a win.
- Aborts (overflow, shift range, bounds, contract violations) stay
  **cold branches to out-of-line stubs**: `jo/jc/ja` to a routine that
  writes the message and raises SIGABRT.  This is deliberate policy,
  not a violation of it: a never-taken, perfectly-predicted branch
  costs ~0 on the hot path and is exactly what production checkers
  (UBSan's `jo`-to-trap) emit.  The branch-free alternative — a
  sticky error flag ORed per operation, tested at statement ends
  (IEEE-754 flags, CERT's As-if-Infinitely-Ranged model) — is the
  planned lowering for the future vectorized/GPU profile, where it is
  the only sound branch-free form; its deferral window must close
  before a poisoned value feeds an address or a branch.

- The emitter keeps a one-register memo: it knows which slot's value
  `rax` holds, skips the reload when the next operand is that slot,
  and forgets at labels, calls, and every join two paths reach — the
  cheapest of register allocations, worth ~3% of code straight away;
  the true linear-scan allocator remains on the plan.

**What stays a branch, on purpose.**  Loop back-edges and loop-bound
checks (predictable, and the loop-carried-dependence research is
unambiguous that cmov loses there); the short-circuit forms with
effectful right sides (semantics); the cold abort paths (above).

## Runtime

A few routines over raw syscalls, emitted before user code:

- `rt_alloc`: bump pointer over `mmap` regions (≥1 MiB at a time),
  state in the RW data segment; no free.  Arrays are `{data, len,
  cap}` descriptors, growth by doubling with copy; strings are
  immutable `{data, len}` descriptors, literals as static descriptors
  in rodata.
- string concat/equality/character-count (the count is the lead-byte
  test materialized with `setcc` — a branch-free body), signed and
  unsigned decimal printing, `write`, and the abort path
  (`write(2, …)`, then `kill(getpid(), SIGABRT)`).
- Planned next (per the policy's "add them to the standard runtime"):
  a Swiss-table hash — 1-byte tags probed 16 at a time with
  `pcmpeqb`+`pmovmskb` — as the runtime shape for `std.hash` when
  hashes reach the compiled subset.

The ELF carries three PT_LOADs: text R+X, rodata R (string bytes,
string descriptors, jump tables), data R+W (globals' initial values
and the allocator state).  No libc, no relocations at run time —
every address is patched at layout.

## The Lexer's Future: the Mask Pipeline

The current lexer is the scalar, table-driven shape of a design meant
to vectorize.  The researched plan for the native/SIMD/GPU lexer, so
attempt 3+ can build toward it:

1. **Phase A over 64-byte blocks**: classify bytes into ≤8 classes
   with two nibble `pshufb` lookups; build one `u64` mask per class;
   derive run boundaries with shift/AND/XOR (`starts = m & ~(m<<1)`),
   string interiors by prefix-XOR (`clmul`), escapes by the
   odd-backslash carry trick; validate UTF-8 in the same pass with the
   Lemire–Keiser three-lookup scheme (~13 GiB/s reported).  All
   cross-block state is a few bits of scan carry — the property that
   makes the same dataflow run on GPUs (masks↔ballots, clmul↔scan).
2. **Phase B**: turn the token-start mask into an index array with
   `tzcnt`/`blsr`, eight at a time straight-line.
3. **Scalar fallback**: the same phases with SWAR on `u64`, and a
   **shift-based DFA** for validation — the whole transition row
   packed per input byte, `state = table[byte] >> (state & 63)`, fully
   branchless at ~1 byte/cycle.
4. **Boundaries**: byte offsets everywhere; character columns computed
   on demand by popcount of lead bytes (`movemask` + `popcnt`), never
   tracked in the hot loop.  Today's lexer already stores byte offsets
   and derives columns; it just does so per byte.
5. **Keywords**: today one hash probe; natively, padded 8/16-byte
   images compared with one masked load + `cmov` of the token id.

## Contracts in the Compiler's Own Source

Per the policy in CLAUDE.md, the compiler practices what it compiles:
helpers carry `@pre`/`@post` — admissible ranges on the type
constructors, alignment and coverage promises on `align_up` and
`build_elf`, condition-code bounds on `cc_of` — and the larger
functions assert their internal milestones: token, node and IR arrays
still in step when a stage hands off, every parameter owning a slot,
every jumped-to label placed before its fixup patches (the assertion
that would have caught a real begin_fn miscount), every function
leaving a code offset behind.  The one recorded exception: the `ty_*`
accessors run for every node the checker touches, so their encoding
invariants are enforced at the constructors rather than per read.
The whole set costs ~3.5% under the interpreter, measured.

## Diagnostics and the Decision Log

The parser recovers at line boundaries (a misparsed statement is
dropped, its hanging block skipped whole, and parsing resumes on the
next line — capped at twenty errors), so one run reports many
mistakes.  Every diagnostic prints its source line with a
character-aligned caret, decoded from UTF-8.  `--diag=json` renders
the same records as JSON; `--log=json` emits the lowering's decisions
— `value-table`, `jump-table`, `ladder-kept` (with cases and span),
`select`/`branched-conditional`, `eager-logic`/`short-circuit` — one
JSON object each with function and line, which is the edit-eval-check
brief's requirement that a program never parse prose.

## Testing

One suite (`tests/run_tests.sh`): bootstrap-language tests run under
the interpreter; the shared programs in `tests/compile/` run under
the interpreter **and** compiled, outputs and exit codes diffed — the
strict-subset rule made executable.  `--impl=` selects a side.
Fourteen shared programs cover the whole core-1 surface including the
stopping paths; `std.implementation` conditionalizes where
implementations may differ.  The diff has caught real bugs on both
sides, including the interpreter's float-precision division.

## Sources

Branchless/codegen: Torvalds on cmov (yarchive), QuestDB cmov-vs-branch
measurements (Zen 4), LLVM `X86CmovConversion`/`SelectOptimize`/
SimplifyCFG thresholds and `isSafeToSpeculativelyExecute`, GCC ifcvt
params and switch clustering (`case-values-threshold`, density ratios),
Wennborg "switch lowering improvements", abseil Swiss tables, folly
F14, CERT As-if-Infinitely-Ranged model, MaskRay "All about UBSan",
warp-divergence characterization (arXiv:2607.23402), Co-dfns, Pareas.
UTF-8/tokenization: Höhrmann's DFA decoder, Pervognsen shift-based
DFAs, Keiser & Lemire "Validating UTF-8 In Less Than One Instruction
Per Byte" (arXiv:2010.03090, simdutf), Langdale & Lemire "Parsing
Gigabytes of JSON per Second" (arXiv:1902.08318, simdjson stage 1),
simdzone design notes, gperf, Lemire on small-set string recognition,
cuDF's GPU FST tokenizer and cuJSON, Mytkowicz et al. data-parallel
FSMs, Levien's stack-monoid GPU parsing notes.
