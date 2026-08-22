Review: Specification Soundness, Test Coverage, Functional Vocabulary
=====================================================================

A point-in-time review (2026-08-19) of three questions: where the
specification admits undefined behavior or other sources of error,
where the test suite has holes, and what the language should add to
enable functional and array-style programming.  The findings marked
**probed** were confirmed by running both implementations while this
review was written; the probe programs are inlined so they can be
rerun.  State at the time of review: 94 interpreter test files green
under `-Werror`, 67 conformance programs byte-identical under both
compilers, twelve suite files running whole as shared conformance
tests, three-stage bootstrap at a byte-identical fixed point.


A. The Specification: Undefined Behavior and Error Sources
----------------------------------------------------------

The specification's central claim (spec.md line 10) is that there is
*no undefined behavior or unpredictable output except when concurrency
comes into play*.  Audited against that standard:

### A1. Mutation during iteration is unspecified — and the implementations disagree today (**probed**) — ~~open~~ **settled**

```
let v : mut i64[] = [1, 2, 3]
let n : mut i64 = 0
foreach x := v:
    n ← n + 1
    if x = 1:
        v.push(99)
std.println("{} {}", n, #v)
```

The interpreter printed `3 4` (three elements visited); the compiled
binary printed `4 4` (it re-read the length every turn and visited the
appended element).  A live conformance break that the byte-diff
methodology never caught, because no test wrote it.

**Settled as the review proposed, and further.**  A walk borrows what
it walks for the whole of the loop, and while that borrow is
outstanding the container's own name is limited to what the borrow
leaves: a shared borrow leaves reading, a mutable borrow leaves
nothing at all.  An iterator made by `.iterate()` holds its array the
same way, to the end of the block the iterator was made in.  Both
implementations refuse the program above, statically, with the same
wording.

The spec chapter is "What a Walk Holds", under Borrowing in a Foreach
Loop; `tests/test_walk_holds.ngpl` holds both implementations to it as
a shared conformance test.  One existing test had to be turned around:
`test_array_iterator_sees_later_writes` asserted that a write through
the array while an iterator was live *was* seen by the iterator, and
the spec's iterator section said the same in prose.  Both were wrong
in the same way — they answered a question that should not have been
askable — and both now say the borrow forbids the write.

### A2. Borrow exclusivity is discipline, not law (**probed**) — ~~open~~ **settled**

```
fn both(a : &mut i64[], b : &mut i64[]):
    a.push(1)
    b.push(2)
...
both(&v, &v)        // accepted by both implementations
```

Two mutable borrows of one array in one call were accepted, as were a
`&` borrow passed where `&mut` was wanted with the write going through,
and an immutable binding lent mutably — the last two under the
interpreter only, which the compiler had always refused.  The effective
rule was that borrows are advisory.

**Settled.**  A call may not hand one thing to two parameters that both
borrow it where either borrow may change it; two shared borrows of one
thing stay fine, because reading does not conflict with reading.  A
by-value parameter is not a borrow and is never part of it, because by
value means a copy — see below.  Both implementations now refuse the
same calls, statically, in the same words, and the interpreter's two
holes are closed with the compiler's own wording.

The spec chapter is "Two Parameters, One Thing", under Call-by-Value
and Call-by-Reference; `tests/test_one_thing_twice.ngpl` holds both
implementations to it as a shared conformance test.

The work turned up a question the spec had answered two ways, and it
has now been decided: **by value means a copy**.  Passing without
copying is an optimization, valid exactly where nothing can change the
original during the call — which, because a `mut` container parameter
is refused, is everywhere but a `&mut` of the same binding in the same
call.  So `f(a : i64[], b : &mut i64[])` called as `f(u, &u)` is
accepted, `a` is the array as it was, and `#a` answers 1 while the
caller's own goes to 2.  Both implementations make the copy there and
elide it everywhere else.  Where the copy is needed and the type has no
copy the implementations can make — an array of arrays, a struct, a
dictionary — the call is refused rather than half-copied, which is a
limitation and is written down as one.

Also turned up: an argument is written `&name` rather than
`&expression`, so `&s.f` beside `&mut s` is not a case that can arise;
the aliasing comparison is between names, and the parser refuses the
borrow of a field first.

What is *not* settled: exclusivity across a call boundary — a function
that stores a borrow somewhere it outlives the call — cannot arise
today, because a borrow can only be a parameter and an argument.  When
that changes, this rule needs a lifetime to go with it.

### A3. Evaluation order is never written down (**probed**) — ~~open~~ **settled**

Arguments, binary operands, tuple elements.  Both implementations
evaluated left-to-right (probed with impure functions printing their
order), so the order was de-facto defined — which is how C got where it
is.  The same for short-circuit `and`/`or`: the keywords were *called*
short-circuit, but no text stated that a decided left side leaves the
right side unevaluated, and the compiled implementation's eager
evaluation of fault-free right sides was sound only if that guarantee
were normative and the fault-free criterion part of it.

**Settled.**  The spec's "Order of Evaluation" says left to right, with
a row per construct; that a decided `and`/`or` does not read its right
side, as a guarantee a program may rely on; that `∧`/`∨` and `⌈`/`⌊`
read both sides always; and exactly what an implementation may evaluate
anyway — a right side free of effects and free of faults, judged as
written, which is the `speculatable` predicate the compiler's
if-conversion already ran on.  `tests/test_evaluation_order.ngpl` holds
both implementations to every row and runs in both suites.

**Probing it found a row that was not agreed after all.**  `v[i] ← e`
read the value before the index under the interpreter and after it
under the compiler — Python's order against the written one — and no
test had asked.  An assignment writes what is on the left, so the left
is where the reading starts: the interpreter now evaluates a target's
own subexpressions before the value.  It is the third divergence this
review's probes have turned up that every gate had passed, and the
second (after A1) that only existed because nobody had written the
question down.

### A4. Stack exhaustion contradicts the spec (**probed**)

The spec defines `std.errors.stack_overflow` (code 102).  In fact the
interpreter reports Python's "maximum recursion depth exceeded" and
compiled binaries die of SIGSEGV on the guard page.  Neither produces
error 102.  Either the spec should say "resource exhaustion
terminates the program; the guard makes it immediate and safe," or
the compiled runtime needs a SIGSEGV handler that recognizes the
guard page and reports in the language's own voice.  Related:
**exit codes on runtime errors are unspecified** — the interpreter
exits 1 where compiled binaries exit 134 (SIGABRT), and the abort-mode
tests assert only "nonzero," so the fork is invisible to the suite.

### A5. Enum distinctness (**probed**)

```
enum E:
    a = 1
    b = 1
```

Accepted by both implementations, and `E.a = E.b` answers `true`.
The spec does not say whether an enumerator is its name or its
number.  If two names may share a value, equality silently conflates
them; for this language the right answer is probably to refuse
duplicate values unless explicitly blessed.

### A6. Division's second failure mode (**probed**)

`INT_MIN ÷ ⁻1` is caught by both implementations (as integer
overflow — correct), but the division chapter discusses only the zero
divisor.  The overflow case, and which error it raises, belongs in
the text.

### A7. Unit conversion is a semantic fork and an overflow risk

The bootstrap converts `km + m` by multiplying through the factor;
the compiled subset refuses the mix outright (recorded in
ANALYSIS.md).  The dimensional-analysis section describes conversion
but never addresses overflow of the conversion multiply.  One
implementation converting while the other refuses is a standing fork
that needs a decision, not just a record.

### A8. Diagnostics are load-bearing but owned by nobody

`@expect` matches message *text*.  Dozens of expectations couple the
suite to exact wording no document specifies, so any rewording is a
silent test break.  The spec already defines stable error codes
(100–106 runtime, 200–299 compile-time) — **nothing emits or checks
them**.  Matching expectations by code instead of text would make
messages freely improvable.

### A9. Smaller items

- Float text exists while floats are unimplemented; rounding ties,
  NaN comparison and ordering, `-0.0 = 0.0`, and print format are all
  unstated.
- The arena never frees; a long-running program's memory is monotone.
  Observable, interacts with no spec text.
- Credit where due: hash iteration order **is** properly specified
  (insertion order), which is the discipline the rest of this list
  asks for.
- Concurrency is the declared UB zone, but the chapter should carve
  sharper: what is a data race over a `@replaceable` binding, what do
  channels promise, what is the memory model between gang members.


B. Holes in the Test Suite
--------------------------

The suite is strong where the project has lived (conformance
byte-diffing, the shared-file mechanism) and weak in one repeating
pattern: **what was verified by hand during development has no
automated guard.**

### B1. The binary-format features have zero tests  *(done)*

> Closed on 2026-08-19 by `tests/compile/run_elf_tests.py`, which the
> compile-conformance runner calls in both modes.  Eleven cases over
> two probes cover the header, the segment permissions and W^X, the
> RELRO region, the non-executable stack and its size, the seven
> sections, the symbol table's local-before-global ordering and
> `sh_info`, an `@export` symbol's binding, a signature's definition
> hash, function extents that lie inside `.text` and do not overlap
> each other, the runtime trimming from both sides, `--stack-size` and
> `--guard-size`, and a `readelf -a` that must not complain.  Nine
> mutations of a good binary were checked to fail it.


The symbol table and signature names, struct definition hashes,
PT_GNU_RELRO and the self-applied seal, the stack reservation and
guard, `--stack-size`/`--guard-size` validation, PT_GNU_STACK,
runtime-routine trimming — all verified manually with `nm`,
`readelf` and gdb when they landed; none asserted since.  A one-file
harness compiling a probe and grepping `readelf -lW`/`nm` output for
the invariants (GNU_STACK present and non-executable, the RELRO page,
an `@export` symbol global and the rest local, an unreachable
runtime routine absent) would lock in roughly ten hard-won properties.

### B2. No differential fuzzing

The A1 divergence survived every gate because both suites contain
only programs someone thought to write (it is settled now, but it took
a review rather than a test to find).  The project's whole method
is byte-diffing two implementations; a small random-program generator
(even ~200 lines emitting well-typed core-2: arithmetic, arrays,
loops, calls) run through the existing both-mode harness would have
found A1 and the unit-arithmetic laxity mechanically.  Highest-
leverage single addition to the testing.

### B3. Abort paths are thin

Five t9x files, asserting only that both implementations fail.  Exit
codes, abort messages, and *which* error fires are unasserted — the
rc 1 vs 134 fork (A4) is invisible.  The spec's error-code table has
no test at all.

### B4. The compiler's diagnostics have no coverage

`@expect` bodies are ignored by ngplc, so only the interpreter's
messages are ever verified.  Every refusal message the compiler emits
— several hundred by now — can rot freely; the conformance runner
checks only that refusal happens.

### B5. The known borrow holes are unpinned

The two interpreter laxities and `&mut`/`&mut` aliasing acceptance
(A2) have no tests documenting current behavior, so a future fix or
regression changes semantics with no tripwire.

### B6. Boundary and adversarial inputs

Sparse coverage at INT_MIN/INT_MAX per width outside t91/t92; no
shift-count-at-the-edge sweep per width; no malformed-UTF-8 *source
file* tests (the shift-DFA can detect malformed input; nothing feeds
it any); no huge-input lexer test; no OOM or arena-growth test.
This review said `tests/output/` held three cases outside the gate
loop; that was wrong when written — it holds 134 and `run_tests.sh`
runs it.

### B7. Property-based tests fit this project unusually well

The interpreter is a ready-made oracle.  Candidates: `@wrap`
arithmetic ≡ mod 2ⁿ; `chars()` then `⧺`-fold ≡ identity on strings;
hashes against a model dictionary under random operation sequences;
`v[⍋v]` is sorted, once grade exists (C2).


C. Language Additions for Functional and Array Programming
----------------------------------------------------------

Already present and good: lambdas with by-value captures, full
currying, `generate`, folds `⌿`/`⍀` with optional seed, listable
threading (`v > 3` answers elementwise), `⍳`, `∊`, `⍴` with matrices,
ranges as values, sets with `∪`/`∩`, `⊃`/`⊇`.  The core-2 gap is
mostly that the FP glyph cluster (`¨`, `⌿`, `⍀`, `√`) is unlexed in
the compiler — closing that is implementation work, not design.  The
*design* gaps, in recommended order:

1. **Boolean-mask selection: `v[mask]`.**  Highest leverage, because
   listable comparisons already produce the masks — `v[v > 3]` is
   filter with no new function machinery, pure data flow, and it
   vectorizes.  APL's compress wearing the existing subscript syntax.
   Works on matrices too (`m[m ≠ 0]`).

2. **Grade, not sort: `⍋v` / `⍒v`.**  Answer the index permutation
   rather than a sorted copy.  Needs no comparator closures to start
   (natural order per scalar type), and composes: `v[⍋v]` sorts,
   `names[⍋ages]` is sort-by-key for free.  Specify stability.

3. **Scan (running fold).**  Prefix sums, running maxima, state
   machines as data flow — converts a large class of remaining `mut`
   loops into expressions.  Name it like `generate` (`scan(f, v,
   init)`) first; a glyph can follow.

4. **Zip / multi-variable foreach.**  Already a recorded wall
   (test_borrow_foreach).  Both forms pay: `foreach a, b := v, w`
   and `zip(v, w) : (A, B)[]` — tuples already carry the pairs.
   Refuse mismatched lengths; this language should not truncate
   silently.

5. **Matrix structure: transpose `⍉`, reverse/rotate `⌽`, folds
   along an axis.**  Matrices can currently only be built and
   indexed.  Transpose first; the others follow once axis handling
   exists.

6. **Outer product** (`f∘.×`-style, or named `table(f, v, w)`).
   Builds a matrix from two vectors; fits directly on the row-based
   matrix representation.

7. **Pipeline `|>` and composition `∘`.**  Syntax over existing call
   and closure machinery — currying already makes `f(a)` a unary
   stage — and it changes how programs read:
   `data |> keep(pred) |> f¨ |> (+)⌿`.

8. **Functional update: `p with {x: 3}`**, and `v with [i: x]` for
   arrays.  The freshness discipline already pushes toward
   immutability; a non-mutating update removes the main remaining
   reason to reach for `&mut`.

9. **Finish sum types and generalized `match`** (already in
   design/sum-types/ and the spec, tagged [FULL]).  Result/Either
   programming is the idiom the `T!` alias currently stands in for.

Deliberately deferred: tacit/point-free trains (parsing ambiguity
out of proportion to the gain) and windowed/stencil reductions
(want the axis machinery from item 5 first).

Sequencing note: items 1–3 are each one primitive on existing
machinery and immediately composable; together with the folds and
listables already present they cover most of what array languages
are reached for.


Actionable Without Design Debate
--------------------------------

Three items need no discussion, only work:

1. ~~Settle mutation-during-iteration (A1) — it is a live
   divergence.~~  Done; see A1 above.
2. ~~Write the evaluation-order and short-circuit paragraphs into the
   spec (A3).~~  Done; see A3 above.
3. ~~Add the ELF-invariants test file (B1).~~  Done; see B1 above.
