# ngplc Attempts 2–3 — What Stands, What Fell Short, What Comes Next

Per step 5 of the process in `CLAUDE.md`.  `DESIGN.md` says what was
built; this says what it proved and where it stops.  Attempt 1's
analysis is `old/attempt1/ANALYSIS.md`; everything it listed as the
frontier has now landed through structs, optionals and hashes.

## What Stands

core-1 compiles and conforms: the sized integer family with faithful
overflow/wrap/shift/division semantics at every width, units-lite
(`¤ptrdiff`/`¤byte`) enforced at subscripts and carried through
arithmetic, growable arrays with borrows and bounds checks, strings
with concatenation/equality/character counts, globals, contracts, and
`std.implementation`.  Core-2 on top of that: structs with methods,
optionals with `match`, arrays of structs, hashes over a probing
runtime table (murmur3-finalizer and FNV-1a hashing, doubling growth)
whose reads answer optionals, tuples returned and destructured on the
struct representation with interned shapes, width-suffixed literals,
and characters with UTF-8 string positions, `.chars()`, `.chr()`
and `.ord()`, struct values that travel — by parameter, return and
binding — on the reference semantics both implementations share, and
`:=` inference from a right side that states its type.
Twenty-nine shared programs run identically interpreted and
compiled, inside the one integrated test suite; the bootstrap suite
stays green with `-Werror`.  The `@test`/`@expect` harness now
compiles too, with the interpreter's options and report format, and
the first five bootstrap test files whose whole surface sits inside
the subset run as shared conformance tests, their `--test` output
matched byte for byte; a sweep showed the remaining 89 lean on
features the subset refuses by name, so the shared list will grow
with the subset rather than by porting.  Two growth batches
aimed at them — ⍳, saturating ⊞⊟⊠, ⊕⊼⊽ and slices, then sized
arrays, ⍴ fills, bool elements and mut value parameters — and both
conform, but the near files keep one more layer each: while-bindings,
statement-level @expect, matrices, element-wise operators.  Array ⧺
broke through: test_concat became the sixth shared file, the first
flipped by a growth batch, taking fresh-array reassignment and the
bare-∅ body along with it.  The lesson stands: the shared list grows
a feature at a time, and each batch is its own conformance win
whether or not a whole file flips.

The control-flow policy is real, not aspirational: comparisons
materialize, `⌈ ⌊` and safe conditionals are `cmov`, `and`/`or` with
fault-free right sides evaluate eagerly, dense ladders emit actual
jump tables (verified in the binary: three tables in the dispatch
test, the sparse ladder correctly left alone), and the only remaining
hot-path branches are loop bounds and never-taken abort exits — both
deliberate, both backed by the profitability research in DESIGN.md.

The conformance diff kept earning its keep: it caught the
interpreter's float-precision division (`(2^64−1) ÷ 3` off by 341),
ngplc accepting `&mut` at call sites the bootstrap refuses, a
unit-less index in ngplc's own codegen, and literal folding wrapping
past i64.

## What Fell Short

1. **Self-hosting is closer but not closed.**  Attempt 3 landed
   structs with methods, optionals with `match`, arrays of structs,
   hashes with their runtime table, tuples with destructuring,
   width-suffixed literals, and characters with UTF-8 string
   positions, `.chars()`, `.chr()` and `.ord()`, and struct values
   that travel by parameter, return and binding.  The compiler's own
   source is now written almost entirely inside the subset.  The
   self-hosting sweep landed the rest of what the source needs:
   container parameters and returns, structs inside structs, stores
   through arbitrary paths, `@dropunit`, global hash tables
   initialized before `@start`, the OS surface `main` stands on
   (args, open/create/read/write/close over raw syscalls), `@start`
   answering the exit status, unit-suffixed literals, and the `byte`
   name; the two `⍴` uses were rewritten as loops.

   **ngplc is self-hosting.**  Three diagnostic rounds separated the
   compiler's own source from the subset: `str[]` elements; then the
   unit and width meetings the bootstrap has always had (a plain
   value takes a measured one's measure; a value-preserving widening
   passes as itself and a narrowing carries a fit check the compiled
   code makes at run time, `IR_NARROW` → `rt_badfit`); discarded
   `pop()`s took explicit defaults; calls grew stack arguments past
   the sixth.  Stage 1 (the interpreted compiler compiling its
   source) now takes ~2¼ minutes; stage 2 — the same compile run by
   the stage-1 binary — takes **49 milliseconds**, stage 3 confirms
   the fixed point (stage2 ≡ stage3 byte for byte, and stage1 ≡
   stage2 besides: the compiler is deterministic whichever way it
   runs), and the native compiler passes all 25 conformance programs.
   The interpreter itself gained the instruments that made the chase
   short — a forward-progress watchdog with heartbeats, per-function
   progress recording (`--fn-stats`) — and then a profile-driven
   optimization campaign in their terms; see the interpreter
   performance section below.  The struct probes settled a fact worth
   recording: the bootstrap's struct values are references — one
   struct behind however many names — so the compiled pointer
   representation conforms by construction, and the subset's
   remaining freshness rules (mut bindings and reassignment) are
   discipline, not representation.  The
   hash runtime is linear probing, not yet the 16-wide `pcmpeqb`
   Swiss-table probe the design planned, and the lexer still decodes
   UTF-8 a byte at a time rather than through the shift-DFA and mask
   pipeline the design researched — correctness first, the SIMD shape
   when the native compiler makes it measurable.
2. **Register allocation is one register deep.**  The emitter's rax
   memo skips reloads (~3% of code) but every value still lives in a
   stack slot; the true linear-scan allocator over the width-annotated
   IR remains the next backend step — compile speed of the *generated*
   compiler will matter once self-hosting closes.
3. **Value-table folding landed** for constant-returning ladders
   (zero control flow, cmov-clamped index, verified branchless in the
   binary); the assignment-armed form (`x ← const` per arm) and
   trailing-expression arms still fall back to jump tables.
4. **The eager-`and`/`or` and select conversions have no cost bound.**
   Legality is enforced; the research's other half (don't speculate
   an expensive arm) is not, because core-1's speculatable set is all
   cheap.  When calls become speculatable (pure, provably
   non-faulting via contracts — the language's own advantage), a cost
   model must arrive with them.
5. **Diagnostics recovered and started talking.**  The parser now
   resynchronizes at line boundaries and reports up to twenty errors
   per run, every diagnostic carries the source line and a caret
   (UTF-8 decoded, character-aligned), and `--log=json` emits one
   JSON object per code-shaping decision — value-table folded,
   jump-table emitted, ladder kept and why, select versus branched
   conditional, eager versus short-circuit logic — the first real
   content of the machine-readable brief.  Still open: cascading
   quality after recovery, and logging layout/width decisions.
6. **The interpreter's speed was the bottleneck, and was fought to
   a workable draw.**  Two quadratics hid in it: argument coercion
   re-measured every array element at every call (each element
   re-parsing its type string through a regex), and `deep_copy_value`
   copied every by-value array argument whole — for the compiler
   compiling itself, the entire source at every `run_str` call.  The
   first fell to memoized type-string parsing and stamping an array's
   element type in place after an identity pass; the second to
   aliasing by-value parameters that cannot be written through (every
   write path is refused, so the copy bought nothing), the spec'd
   copy kept for `mut` parameters.  On top of that, dispatch-table
   rounds: the two fifty-case `isinstance` ladders became one-probe
   dict dispatch on the node's class (handlers extracted mechanically
   by an `ast` analysis accepting only blocks whose every path
   returns or raises), method calls check the struct and array cases
   first, two plain integers skip straight to their operator, foreach
   walks an array's live list rather than a copy (which is also what
   the compiled code does), and the small values every program leans
   on are pooled.  The self-compile went: unbounded (killed at 28
   minutes, still lexing) → 7 min → 4m10s → 2m58s → **2m18s**, the
   produced binary byte-identical at every step and the full suite
   green after every batch.  What remains in the profile is diffuse
   (`eval_expr` prologue, per-call environment setup, position
   tracking); the next real step there would be a bytecode-style
   pre-compilation of bodies — or simply using the 49 ms native
   compiler, which is the point of self-hosting.

## Bootstrap Gaps Found This Round

Recorded in TODO-bootstrap.md as they were found: the currying hole
(too few arguments curry even into a non-function type), global
initializers unable to call functions defined below them, `≤`/`≥`
unlexed, units refused on struct fields, `std.args.get` raising
instead of answering `∅`, and no error stream (`std.eprintln`) so
ngplc's diagnostics go to stdout.

## The Plan for Attempt 3 (sketch)

1. Structs by value: `@repr`-style layout in slots or heap, field
   access, `impl` methods with `&self`/`&mut self` — the single
   biggest unlock toward self-hosting.
2. Optionals as values and `match` on them; then hashes with the
   Swiss-table runtime; then `char`, string indexing and `chars()`
   over the shift-DFA UTF-8 core.
3. Linear-scan register allocation over the existing IR; value-table
   folding of constant-armed ladders.
4. Parser error recovery with synchronization at statement starts;
   source excerpts with carets; the machine-readable decision log.
5. Grow the shared suite with every step; the interpreter stays the
   semantic authority.
