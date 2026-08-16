# ngplc Attempts 2–3 — What Stands, What Fell Short, What Comes Next

Per step 5 of the process in `CLAUDE.md`.  `DESIGN.md` says what was
built; this says what it proved and where it stops.  Attempt 1's
analysis is `old/attempt1/ANALYSIS.md`; everything it listed as the
frontier except structs/optionals/hashes has landed.

## What Stands

core-1 compiles and conforms: the sized integer family with faithful
overflow/wrap/shift/division semantics at every width, units-lite
(`¤ptrdiff`/`¤byte`) enforced at subscripts and carried through
arithmetic, growable arrays with borrows and bounds checks, strings
with concatenation/equality/character counts, globals, contracts, and
`std.implementation`.  Fourteen shared programs run identically
interpreted and compiled, inside the one integrated test suite; the
93-file bootstrap suite stays green with `-Werror`.

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
   structs with methods and optionals with `match` — the two largest
   gaps.  The compiler's own source still uses hashes, tuples,
   `str.chars()`, arrays of structs, and struct-typed by-value locals
   copied around.  The gap, in dependency order: arrays of structs →
   hashes (the Swiss-table runtime) → tuples → chars and string
   indexing (the UTF-8 machinery DESIGN.md plans).
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
6. **The interpreter remains the only parallelism-free bottleneck**:
   compiling the 14-program suite takes minutes under the tree
   walker.  The per-function pass structure is ready for the
   parallel compile the brief demands, but only the native compiler
   will deliver it.

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
