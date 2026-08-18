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
Thirty-three shared programs run identically interpreted and
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
conform, but the near files keep one more layer each: statement-level
@expect, matrices, element-wise operators, multi-variable zip
foreach (the wall test_borrow_foreach ends at, past the
write-through references themselves — test_while_binding flipped
whole, the seventh shared file), and directory objects (which fell
in their own batch — `cwd()` as a value, a `getdents64` runtime
walk, entry fields, boxed `next()` and optional equality).
test_iterator held out one more day on a bootstrap hole — the
interpreter admitted `∅` as an element of a plain `i64[]` literal,
which a flat compiled array cannot represent — until the authority
itself was corrected: the interpreter now refuses a `∅` or `∃`
element in an array literal, the quirk test became an `@expect`,
and test_iterator flipped whole as the eighth shared file.  The
flip also caught a silent divergence the first conformance pass
missed: ngplc had given `std.filetype.*` the kernel's `d_type`
bytes where the interpreter holds the `S_IF*` constants as a
`filetype` enum — both self-consistent, so comparisons matched
byte for byte until a test asserted the values themselves.  The
subset now carries a `filetype` type of its own (S_IF values, one
`shl 12` in the runtime walk, equality but no order, untyped
literals meeting it by value, printing refused by name), and the
lesson is sharper than the first one: internal consistency can
hide a divergence, and only asserting the authority's actual
values surfaces it.  Matrices landed next — rank-2, rows as shared
descriptors, tuple-⍴, multi-index as a parser desugar, `.shape`,
extent-checked literals — all on the existing array runtime with
zero new IR and zero new runtime helpers; the probe conforms byte
for byte, but the matrix test files still lean on bare range
values (`(2, 4) ⍴ (1…8)`) and `generate` with lambdas.  Range
values then fell in their own batch — expressions at the spec's
precedence, a three-slot box, the same sign-agnostic loop the
foreach header always used, `⍴` fillers that materialize and cycle
— and lambdas followed in the next batch: λ literals with by-value
captures, named functions as values, closure boxes with the code
address in slot 0, indirect calls, and `generate` over ranges, all
conformant byte for byte on the first probe run.  Currying
followed at once — a partial is another closure box holding a
per-site shim, the bound values and the source box, so partials of
partials compose with no shim knowing what it wraps — and
test_generate flipped whole as the ninth shared file.  Matrix
column selections still hold test_matrix_param.  Generic `T'`
signatures and `@replaceable` followed — one shape per program,
bound by the first call, the body checked on demand with the
caller's scopes parked; capture discipline enforced with the
function's value-box behind the captured name — Optional and
expected answers followed — auto-boxing returns, the `?` early
answer, bare division under an optional — and multi-statement
lambda bodies closed the distance: **test_lambda flipped whole as
the tenth shared file**, the heaviest yet at 44 entries spanning
lambdas, currying, generics, @replaceable, optional answers and
block bodies.  The flip also carried `:=` globals born of function
values (built by the ginit machinery hashes already use) and calls
through a global's box.  The lambda campaign that began at "the λ
byte is not even lexed" is complete.

The generated binaries then stopped borrowing the kernel's stack:
`_start` reserves `guard + stack` of address space, opens the stack
part, and stands on it, so an overflow faults on a guard that is
there by construction rather than by the kernel's grace — verified
in a live process map, where the fault lands exactly on the guard's
top edge.  The static half is the part worth keeping: the compiler
knows every frame it emits, so a frame that could step over the
guard in one `sub rsp` is refused at compile time with the size to
raise, which is the project's rule applied to its own code
generation rather than to the language.  `PT_GNU_STACK` closes the
executable-stack fallback.

The process environment followed, and with it the first program
written to be a program rather than a test: `examples/printenv.ngpl`
is six lines, and its output matches the interpreter's and
`/usr/bin/printenv`'s byte for byte on an environment carrying empty
values, embedded spaces, embedded `=` and UTF-8.  The runtime
ordering trap caught the batch once more — a routine's negative id
is its index into `rt_off`, so a pair emitted anywhere but last
answers as some earlier routine — which is the third time that
particular shape has bitten in this project and an argument for
having the emission assert the id it is filling rather than only the
count.

The auxiliary vector followed the environment it sits above, giving
`std.process` its seven members in both implementations: the
interpreter parses `/proc/self/auxv`, which is the vector itself,
and the compiled program walks the block the kernel left on its
entry stack.  Both were checked against the kernel's own account of
the same values through `LD_SHOW_AUXV`, and `AT_EXECFN` proved to
be the path as given rather than a resolved one — a program started
as `./pr.bin` says so.  The one place the implementations part is
`exec_filename`, which names the interpreter under one and the
program under the other, because that is what it means; the
conformance test asks the values of everything else and only
invariants of that.

The data segment then split three ways — never written, written
only before `@start`, written throughout — with the middle kind
marked `PT_GNU_RELRO` and sealed at run time by the program itself,
following its own headers rather than a hardcoded address.  Two
things had to be true for that to work and neither was: the image
did not map its own program headers, so `AT_PHDR` pointed at
nothing (fixed with a read-only `PT_LOAD` of the first page, which
is what every real linker emits and what makes the kernel's
`AT_PHDR` meaningful); and the runtime-routine ordering trap struck
for the fourth time.  That one is now closed for good: every
routine names the id it fills and is held to it by an assertion, so
a routine emitted out of turn stops the compiler instead of
answering as some other routine.  The seal was checked in a live
process, where the relro page reads `r--p` while `@start` runs and
the allocator's page beside it stays `rw-p`.

The images then gained a symbol table, and with it names: every
function is called by the normalized spelling of its signature, and
a named type by its own name and a hash of its definition, so
`nm` on the compiler shows its 358 functions with its own
`Ast#5e2a2a627f6130fe` and `Toks#2f5dc6c197ec76b9` among them.  The
hash is deep — changing a struct a field reaches through changes
the hash of the struct that reaches it — and terminates on a
definition that refers to itself.

Two divergences surfaced while writing it, both in the direction
that matters.  ngplc accepts `plain + ptrdiff` and `plain < ptrdiff`
where the bootstrap refuses both ("cannot + typed integer i64
without unit with unit ptrdiff"), so the compiler is **more**
permissive than the authority on unit arithmetic — the forbidden
direction, and the first such gap this project has found rather
than reasoned about.  It went unnoticed because ngplc's own source
relied on the laxity in exactly the lines that provoked it.  Second,
the bootstrap flattens one level of re-borrow but not two: a
`&mut u8[]` handed on twice arrives as a `RefValue` with no methods.
The second is recorded and worked around; the first was fixed in
the batch that followed, and the fix is worth the record.

The compiler now decides what a measure may meet per operator, as
the bootstrap does: a sum, a difference, a minimum, a saturating
sum and every comparison want their sides measured alike, since a
plain number is not a length; a product scales, so one measured
side and one plain keeps the measure while two measured sides make
a measure of their own — `ptrdiff×ptrdiff` — which core-2 has no
way to write down and now refuses by name; a quotient divides the
measures out, so two alike cancel to a bare count, while a
remainder keeps what was divided.  A conditional stays lax, because
the bootstrap is lax there: it hands one side on rather than
operating on both, and lets the binding say what it is.  Twenty-five
combinations were compared against the authority one by one, and
all twenty-five now agree.

The surprise was where the laxity actually lived.  Tightening the
rule lit up 221 places in the compiler's own source — and every one
of them was a single unrelated bug: the wanted type was being pushed
into *both* sides of a product, so the untyped `1` in
`(pos + 1) × 1¤ptrdiff` came out measured and was then added to a
plain `pos`.  Not pushing a measure into a product's operands fixed
all 221 at once and left the source untouched.  A rule that had
looked like it needed a wide sweep needed one line, which is an
argument for finding out what the errors have in common before
starting to fix them.

The binaries then stopped carrying the runtime they do not use.
The routines are emitted after the program rather than before it,
so what the program calls is known by the time they are laid down,
and a call graph extracted from the emitter's own text closes over
the rest.  Skipping is one switch over the byte sink and the fixup
recorders, so no part of the emission code had to learn about it.
The safety is the part worth keeping: a skipped routine is left
without an address, so a call that reaches for one stops the
compiler at resolution — verified by removing an edge from the
table by hand, which halts the build instead of emitting a jump
into whichever routine happened to follow.  A program that does
nothing now carries 11 of the 44 routines and the compiler itself
33, and the smallest binary fell from 22664 bytes to 17424.
The interpreter's `println` of a range leaked the implementation's
`RangeValue(3…7)` spelling and now answers the language's `3…7`.  The batch also caught a quiet
acceptance bug through self-hosting: the bootstrap reserves every
`iN`/`uN` spelling with a nonzero width as a type name, and ngplc
let `i2` name a loop counter; now both refuse alike.  Array ⧺
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
