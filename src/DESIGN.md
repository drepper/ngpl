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
- **arrays of structs** `S[]`: the element is the struct's pointer, so
  the array machinery carries over unchanged; `v[i].f` reads and
  stores, whole-element replacement by a fresh literal, `&`-borrowed
  walks, and an element's own array growing through `v[i].items.push`.
- **hashes** `std.hash(K, V)` — K a plain integer type or `str`, V any
  core scalar, `str`, or struct: born from a typed literal
  `⸨k: v, …⸩`, read by `h[k]` answering `V?` (absence composes with
  `??` and `match` for free), written by `h[k] ← v` on a `mut` binding
  or `&mut` borrow, asked by `k ∊ h` and measured by `#h`; handed
  around by borrow like the other containers, never copied, reassigned
  or returned.  The type packs as `8192 + ki×2048 + V` with `ki`
  encoding the key's width/signedness or str-ness — a band disjoint
  from the arrays' `4096 + elem` (elements stay below 4096), so each
  `ty_is_*` predicate answers alone, in any order.
- **tuples** `(T1, T2, …)` of plain integers, truth values, strings,
  structs and optionals: built by a literal whose type the binding or
  the enclosing return states, handed back by functions and methods,
  taken apart by `let (a, b) := …` (`_` discarding, `mut` naming
  changeable parts, a stated `: (…) =` type welcome), asked by a
  written-out index `t[0]` and counted by `#t` — both settled at
  check time, so the index is a field load and the count a constant.
  The representation is the struct's: a pointer to one slot per
  element, `IR_SNEW`/`IR_FSTO`/`IR_FLD` reused whole, zero new IR ops
  and zero new runtime code.  Shapes intern into a table in the Ast
  (band `26624 + tidx`), so type equality stays one integer compare.
  A tuple travels by value and never by parameter, borrow, global,
  optional, array, hash or struct field — each refused by name.
- **width suffixes** `7i64`, `200u8`: the lexer closes the literal's
  type (the code rides in the token as `big + 2×type`), the checker
  adopts it through the same range check as contextual settling.  The
  bootstrap requires them inside tuple literals in return position,
  so the shared subset now has them everywhere.
- **characters** `char`, a Unicode scalar value in a slot: literals
  `'a'`/`'λ'`/`'\n'`/`'\u{1F389}'` lex as closed-type tokens on the
  same `big + 2×type` ride as a suffix; `.chr()` crosses from any
  integer (three refusals — negative, past 0x10FFFF, surrogate —
  folded on literals, two cold never-taken branches at run time) and
  `.ord()` crosses back to `u32` for free; `s[i]` answers the
  character at a ¤ptrdiff position and `.chars()` lays a string out
  as a `char[]`, both over real UTF-8 in the runtime; `foreach` walks
  a string's characters; `⧺` joins characters into strings; the six
  comparisons order by code point through the ordinary signed path
  (code points stay below 2^21).  Character arrays and tuple elements
  ride the existing machinery; hashes of them wait.
- **struct values travel**: the bootstrap's structs are references —
  every probe shows one struct behind however many names — and the
  compiled pointer representation is the same thing, so structs now
  pass by value as parameters, return from any expression, and a
  read-only binding may name a struct held in an array element, a
  hash, a tuple, an optional or another binding, all with zero new
  code.  The discipline that remains: a `mut` struct binding and a
  struct reassignment must be born fresh (a literal or a call), so a
  let whose right side visibly names shared data cannot create a
  mutable alias; `&mut` stays the way to change what is shared.  (A
  call may still answer a shared struct — the reference semantics
  make that identical in both implementations.)
- **`:=` inference**: `let x := e` and `let x : mut = e` take the
  binding's type from a right side that states it — a call, a
  suffixed or self-stating literal, any settled expression — while
  what states nothing is refused with the stated-form cure spelled
  out (`settles on 'int'; state a sized type, as 'let x : i64 = …'`).
  The per-kind birth rules ride along unchanged: hashes and arrays
  are still born from their literals, a mut struct binding still
  born fresh.
- **what self-hosting asked for**: containers travel like structs do
  (arrays and hashes as by-value parameters and returns — the same
  reference-semantics argument, the same non-mut discipline on
  bindings); structs may hold structs, and a store reaches through
  any postfix path (`self.a.nkind[id] ← v` — the statement parser now
  parses the expression first and turns a following `←` into the
  store its shape names, retiring the old name-only target ladder);
  `@dropunit` passes a measured number through unmeasured; and an
  immutable global hash of constants is built by a synthesized init
  function the image runs before `@start` — the one runtime-
  initialized global kind, because the compiler's own keyword and
  glyph tables want exactly that.
- **the OS surface `main` stands on**: `std.args.all()` (argv[1..] as
  a `str[]`, the kernel's argc/argv captured at the entry rsp into
  the data segment), `std.fs.cwd().open_file(p)` answering `File?` so
  absence composes with `??` and a `@noreturn` default, `create_file`
  aborting rather than answering, `read_file` (fstat + read loop +
  widening into slots), `write` (narrowing + write loop), `close`,
  and `std.arena.allocator()` as an accepted token — the bump
  allocator is the arena.  `@start` may answer a plain integer, which
  `_start` hands to `exit`.  Unit-suffixed literals (`1¤ptrdiff`,
  `0¤byte`) close their type at the lexer like width suffixes, and
  `byte` names `u8`.
- **finding, holding, slicing**: `container ⍳ wanted` answers the
  position as an optional ¤ptrdiff (string elements compared by
  content), `⊞ ⊟ ⊠` hold arithmetic at the type's edge — narrow
  widths compute exactly in 64 bits and clamp by compare, the full
  width reads the flags the op leaves, the saturation target chosen
  by the operands' signs before the flags matter, selects throughout
  and never a branch — `⊕ ⊼ ⊽` finish the logic family as one
  bitwise op and at most one xor, and `v[a…b]` takes a fresh
  sub-array, both ends included, `hi < lo` empty, an end outside the
  array out of range.
- **the test harness**: `@test` functions compile into the binary and
  run before `@start` — silently when they pass, the first failing
  assertion stopping the run.  The binary honors the interpreter's
  own options: `--skip-tests` bypasses them, `--test` reports each
  test and the summary on the error stream in the interpreter's
  exact format and exits without running `@start`; a synthesized
  argument filter keeps both flags out of `std.args.all()`, as the
  interpreter keeps its options out of a program's arguments.  An
  `@expect` definition — a function or global expected to draw
  diagnostics — is parsed and left uncompiled (the interpreter is
  where the expectation itself is verified); a reference to one is
  answered with "expects errors under @expect and was left
  uncompiled", and `--test` still reports it in the suite's shape.
  The driver and filter are ordinary synthesized IR functions, so
  they cost two small functions in every image and nothing at run
  time when no flag is given and no test exists.

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
- the hash table behind `std.hash`: one allocation holding a
  40-byte descriptor `{ctrl, kv, count, cap, keystr}`, one ctrl byte
  per slot (0 empty, 1 held — mmap's virgin zero means a new table
  needs no clearing), 16-byte key/value pairs, capacity a power of
  two, linear probing, growth by doubling at 7/8 load with rehash.
  Integer keys hash through the murmur3 finalizer, `str` keys through
  FNV-1a with equality by `rt_streq`.  `rt_hfind` is the one probe
  loop; get/put/membership/grow ride on it (it leaves the descriptor
  and key in preserved registers for them).  A get boxes the value
  into a fresh optional.  The full Swiss-table shape — tags probed 16
  at a time with `pcmpeqb`+`pmovmskb` — remains the planned upgrade;
  the descriptor already carries what it needs.
- the character quartet: `rt_stridx` (skip to the i-th lead byte —
  each character's length from three materialized `setae` adds, no
  branch — then decode), `rt_chars` (decode a whole string into a
  fresh array, capacity bounded by the byte length), `rt_charstr`
  (encode one scalar as 1–4 UTF-8 bytes in a fresh string), and the
  `rt_badchar` abort stub behind `.chr()`'s two cold checks.

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

## The Bootstrap Chain

`build/bootstrap.sh` runs the chain the process prescribes: the
interpreted compiler builds stage 1 (~2¼ minutes), stage 1 builds
stage 2 (49 ms), stage 2 builds stage 3, and stages 2 and 3 must
match byte for byte before the verified stage-2 binary installs as
`build/ngplc`.  Stage 1 matches them too: the compiler is
deterministic whichever way it runs.  The build caches against the
source's timestamp, so the suite's native runs find it ready.

The 2¼ minutes is the residue of a profile-driven campaign on the
tree-walking interpreter, run entirely with its own instruments
(`--timeout`, `--heartbeat`, `--fn-stats`) after the first
self-compile attempts either looped or crawled:

- two quadratics fell — per-call re-coercion of every array element
  (memoized type parsing, element types stamped in place) and the
  by-value array copy (read-only parameters alias; every write path
  through them is refused, so the copy bought nothing)
- the two fifty-case `isinstance` ladders became one-probe dict
  dispatch on the node's class, the handlers extracted mechanically
  by an `ast` analysis that accepts only blocks whose every path
  returns or raises
- foreach walks an array's live list rather than a copy — which is
  also what the compiled code does — and the common small values
  (integers, the two booleans, ∅) are pooled singletons

Each batch was gated on the full suite and on the stage-1 binary
staying byte-identical.  The arc: unbounded → 7 min → 4m10s → 2m58s
→ 2m18s.

## Testing

One suite (`tests/run_tests.sh`): bootstrap-language tests run under
the interpreter; the shared programs in `tests/compile/` run under
the interpreter **and** compiled, outputs and exit codes diffed — the
strict-subset rule made executable.  `--impl=` selects a side:
`bootstrap`, `compiled` (ngplc under the interpreter), `native` (the
self-hosted `build/ngplc`, the whole sweep in ~2.4 s), `both` (the
default) or `all`.  Twenty-seven shared programs cover the whole
core-2 surface including the stopping paths, and five bootstrap test
files whose whole `@test` surface sits inside the subset run as
shared tests besides: compiled, run with `--test`, and their stdout,
stderr and exit code must match the interpreter's byte for byte.
That list grows as the subset grows — most of the other 89 files
lean on features the subset refuses by name (floats, generics,
combinators, custom units, comptime), which is what keeps them
bootstrap-only.  `std.implementation` conditionalizes where
implementations may differ.  The diff has
caught real bugs on both sides, including the interpreter's
float-precision division and the hash type band hiding inside the
array band.

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
