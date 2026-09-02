# The compiler without flow control: what copies, what loops, and the operators that would take their place

An analysis of `src/` (37 files, 1.6 MB) made on 2026-09-02, after the
name-lookup and match rounds.  The question asked was: where does the
compiler copy data it need not, which of its tables could be constant
globals, which of its loops and branches are an array operation in
disguise, and what operators would let it be written as array
operations strung together.  The numbers are counts over the source
as it stands; the section at the end says what can be done today and
what needs the language to grow first.

## 1. What copies at a call

**Little, and what does is required.**  A struct travels as a pointer
to its slots and an array as a descriptor, so passing either copies a
word; today's borrow sweep made that explicit on 430 signatures
(`&elf.Target` on 368 of them) without changing what moves.  The one
place a call copies an array is `lower.copied_arg` (lower.ngpl:2082):
the checker's `check_alias` (check.ngpl:3630) finds a call handing one
thing over twice with one side mutable, and the by-value side is then
cycled to its own length (`acyc`) so the callee cannot watch its
argument change under it.  That copy is the semantics, not waste; it
is decided per call site and made only there.

What remains of copying in the source is explicit and small:

| where | what | lines |
|---|---|---|
| check.ngpl:3250–3276 | nine parallel scope arrays copied element by element to park the caller's scopes while a generic body is checked, and copied back after | 9 loops |
| symbols.ngpl:49 | `seen` copied by pushing | 1 loop |

The nine are one idiom: a scope *mark*.  Remembering the nine lengths
before the shaped body and truncating to them after would replace
eighteen loops with two statements and copy nothing, since a callee's
declarations only ever extend the arrays.  Until then, a slice
(`v[0¤ptrdiff…#v]`) is one operation where each loop is one per
element, which is what the IR columns got in commit b55cd8b.

**Tables rebuilt on every call.**  Seventeen functions answer a
literal and nothing else, and every call builds the array again:

| function | file | type |
|---|---|---|
| `hash_algs`, `hash_digest_bytes` | ast.ngpl:236,243 | `str[]`, `i64[]` |
| `diag_codes` | check.ngpl:6279 | `i64[]` |
| `ev_cmp_admits` | comptime.ngpl:217 | `i64[]` |
| `rt_names`, `utf8_dfa_words`, `rt_edges` | emit.ngpl:980,1089,1100 | `str[]`, `i64[]`, `i64[]` |
| `sha_k`, `sha_h0` | sha256.ngpl:24,45 | `u32[]` |
| `builtin_enum_names/widths/members/values` | types.ngpl:61–75 | `str[]`, `i64[]` |
| `unit_names/decays/none_names/marks` | types.ngpl:124–146 | `str[]`, `i64[]` |

`ir.IR_READS` and its two siblings were the same shape and are
globals now (commit ad8fd66 taught the compiler an immutable global
array of constants).  Fourteen of these seventeen can follow today.
`elf.targets()` is the eighteenth and different: six struct literals,
built at five call sites, and a global cannot hold a struct literal
yet -- the init function that lays a global dictionary or array down
before `@start` would have to lay a struct down too.  It should; the
six targets are the most-read constant the backends have.

## 2. What the loops are

559 `foreach` and 180 `while`, read by shape:

| shape | count | what it is | operator |
|---|---|---|---|
| fill or copy: one `push` of a constant or of the element | 68 | `n ⍴ x`, or a slice | **exists in core-2** |
| find: `if a[i] = x: return i` | 58 | `a ⍳ x` | exists in core-2 for an array of values; a field (`fns[i].name`) wants `¨` first |
| map: `out.push(f(x))` | 51 | `f ¨ v` | in the language, not in core-2 |
| reduce: `acc ← acc + x`, `all ← all and p` | 5 | `+⌿ v`, `∧⌿ v` | in the language, not in core-2 |
| amend: `a[i] ← expr` over a range | 9 | `a[ix] ← w` | proposed |
| zip: two pushes per turn | 7 | `f ¨ v` answering a pair | needs tuples from `¨` |
| nested loops | 52 | flatten, outer product | `⧺⌿ (f ¨ v)` |
| `while #v > n: pop` | 34 | truncation | `v[0…n]`, or the reset of b55cd8b |
| index walks `while i < n` | 22 | a `foreach` written by hand | -- |
| everything else | 361 | see below | |

The 361 "other" loops sampled at random are mostly five things:

1. **filter**: `if v ≠ ⁻1: out.push(v)` (incr.ngpl:423) -- a mask and
   a gather.
2. **last index matching**: `if path[i] = '/': cut ← i`
   (imports.ngpl:178) -- `⍸` on a mask, then its last element.
3. **parallel-array init**: three `push(⁻1)` per turn (check.ngpl:1830)
   -- three `n ⍴ ⁻1`.
4. **strided reads of the AST's `extra` table**:
   `extra[(off + 1 + i × 2)]` -- 35 such expressions, each inside a
   loop over the pairs or triples an offset introduces.  A stepped
   slice (`extra[lo…hi…2]`) is a view of one column of that table, and
   the loop becomes an operation over the view.
5. **masked stores**: `if t < 0: rt_need[…] ← 1` (codegen_t.ngpl:335)
   -- an amend under a mask.

And two idioms that are not loops but hold loops in place:

- **`if #v > 0:` around a loop.**  103 of these, 75 directly wrapping
  a `foreach`.  They date from a compiler that walked `0…n` downward
  when `n` was 0; both implementations run an empty range zero times
  today (checked: `foreach i := 0…0`, `foreach x := []`, and
  `0¤ptrdiff…#[]` all answer 0).  The guards are dead flow control and
  can go now, all 103.
- **linear finds over tables that only grow.**  The checker's five went
  to hash tables in b55cd8b (native self-compile 1.14 s → 0.80 s).
  Twenty are left, and three of them are hot: `lower.intern`
  (lower.ngpl:146; 83 call sites; every string literal and every
  message the compiler emits is looked up by walking every string
  interned so far), `comptime`'s `fn_index`/`global_index`
  (comptime.ngpl:338, 733), and the parser's seven name tables
  (`enames`, `snames`, `unames`, `tanames`, `mel`, `mtab.names`,
  `mtab.bname`; parse.ngpl:601–698).  One mechanism (`names.Names`)
  answers all of them.

## 3. What the branches are

3,928 `if`/`elif`:

| shape | count |
|---|---|
| value-form `if c: a else: b` | 492 |
| guard `if c: return …` | 751 |
| `x = ⁻1` sentinel tests | 92 |
| `if #v > 0` guards (dead) | 103 |
| `elif` arms | 531 |
| the rest | 2,062 |

The value form already compiles to a conditional move (`lower_ife`:
"read both and choose") -- it *is* the select operator, and needs no
new glyph.  What keeps the rest as branches is mostly the sentinel
convention: 42 `return ⁻1`, 92 tests of `⁻1`, and 6 `?? ⁻1` turning
an optional back into a sentinel.  `⍳` answers `∅`; a table lookup
answers `∅`; the `??` chain composes them, and a chain is straight-line
code.  Writing the finds and lookups as optionals rather than
sentinels is what would let the guards go, and it is the same change
that lets them be operators.

The 751 guards are early exits from validation, most of them in the
checker (`if ty ≠ want: derr(…); return`).  Those are the checker's
job and stay; the CLAUDE.md policy is to keep the hot path straight
and move the cold path out, which a guard does.

## 4. The operators, in the order they pay

Each is named with the loop shape it removes and how many of them
there are.  The first three exist in core-2 and are a rewrite; the
rest are additions to the checker, the lowering and the runtime, and
the full language's spelling is used where it has one.

1. **`n ⍴ x`** (exists) -- 68 fill loops, and the parallel-array inits
   inside the "other" 361.  `n ⍴ ⁻1` is what `foreach _ := 0…n:
   v.push(⁻1)` says.
2. **`v[a…b]`** (exists) -- the 10 copy loops; `v[0…n]` for the 34
   truncations by `pop`.
3. **`a ⍳ x` answering `∅`** (exists) -- the finds over arrays of
   values, written `a ⍳ x ?? …`.  For finds over a field, see 5.
4. **`f ⌿ v`, `f ⍀ v`** -- reduce, as the spec has it (§7094): `+⌿`,
   `⌈⌿`, `∧⌿`, `∨⌿`, and `⧺⌿` for flattening and for joining strings.
   Five reduce loops and the string joins; `⧺⌿` also serves the nested
   loops that push every element of every inner array.
5. **`f ¨ v`** -- each, as the spec has it (§7166), with `f` a named
   function or a `λ` (both are values in core-2: `Nk.fnval`,
   `Nk.lambda`).  51 map loops; and a find over a field becomes
   `(name ¨ fns) ⍳ s`.  The runtime side is one call per element,
   which the lowering can emit as a loop the source no longer has to
   write; the pay-off is in what the checker can then see -- a `¨` has
   no early exit, no accumulator and no index to get wrong.
6. **`⍸ b`** -- where: the indices at which a boolean array is true.
   With 7:
7. **`v[ix]`** -- gather: subscript by an array of indices answers an
   array.  `v[⍸ (v ≠ ⁻1)]` is the filter; `(path = '/')` is a mask,
   `⍸` of it the positions, and the last of those the `cut` that
   imports.ngpl:178 walks for.  This is also the table lookup that
   replaces an `if` cascade on a dense key -- `NAMES[k]` where the
   cascade said `if k = A: … elif k = B: …` -- which `match` already
   does for enumerations by jump table; gather does it for data.
8. **`v[ix] ← w`** -- amend: the store side of 7.  Nine amend loops
   and the masked stores.
9. **stepped slices `v[lo…hi…step]`** -- a view of one column of a
   packed table.  35 strided reads of `extra`, every one of them
   inside a loop that 5 or 7 would then absorb.  `foreach` already
   takes `lo…hi…step`; the slice would take the same range.
10. **`⍋ v`** -- grade: the permutation that sorts.  One insertion sort
    (codegen_t.ngpl:309) written by hand for "a few dozen entries",
    and the SBOM's ordering.
11. **`sep ⋈ parts`** -- join with a separator.  The one concatenation
    operator the compiler wants and does not have: check.ngpl:2197
    and its kin write `acc ⧺ (if i = 0: "" else: ", ") ⧺ e` -- a branch
    per element to leave one separator out.  `⧺` is enough for arrays
    (`a ⧺ b` is `acat`, and `⧺⌿` flattens); strings want the separator
    form.  Spelling: `⋈` (U+22C8, "bowtie") is free, or `⧺` with a
    separator on the left by type, which the checker can tell apart.

What these do not cover, and should not: the 751 guards (validation
leaves early by design), the checker's recursive descent over the
tree (a `match` per node kind, which is a jump table), and the
emitters' instruction selection (a `match` per opcode).  Those are
dispatch, and a jump table is already the branch-free form of
dispatch.

## 5. What can be done now, in order

Without touching the language -- **done on 2026-09-02**, every step
holding the fixed point and compiling the 95 conformance programs to
the same bytes:

- The 71 `if #v > 0:` guards that wrapped one loop over the array
  are gone; the 31 that guarded something else stay.
- `n ⍴ x` for the seven fills whose array was born beside them (the
  other fills push into an array that already holds something);
  slices for the nine scope copies; `v ← []` for the 26
  pop-to-empty loops.  A `mut` array may not be born of a slice
  (the checker asks for a literal or a call), so the one copy that
  is extended afterwards stays a loop.
- Nine literal tables are global constants: the diagnostic codes,
  the runtime's names and edges, the UTF-8 table, the SHA-256
  constants, the hash algorithms, the comparison-admits table.  The
  other eight -- the unit and builtin-enum seeds -- stay functions
  **on purpose**: a parse seeds its own tables from them and then
  pushes to those tables, and a global array is one storage, so a
  shared seed would carry one file's declarations into the next.
  `targets()` waits on struct literals in globals.
- `names.Names` grows now (slots double at half full, every name
  placed again) and a name may answer a value of its own
  (`add_at`), so a table can stand beside an array that holds a
  string more than once and answer the first, as the walk did.
  `lower.intern`, the parser's enum, struct, unit and type-alias
  tables and comptime's function and global lookups probe it.
- The scope mark is not done: `check_fn`'s epilogue clears the
  scope arrays to zero and `scope_floor > 0` means "inside a
  lambda" elsewhere (check.ngpl:3108), so a mark would change what
  the shaped body sees.  The nine copies are slices instead.

Two divergences between the implementations came out of it, both
fixed in the interpreter: `⍴` refused a truth value or a string as
the filler and a measured count on the left, where the compiler
accepts both (t84_reshape_fills).

With the language grown (in this order, each one measured on the
self-compile before the next):

- `⌿`/`⍀` and `¨` into core-2: the two operators the spec already
  defines and the compiler cannot yet write with.  Together they take
  the maps, the reduces, the joins and the nested pushes -- about 120
  loops -- and give `⍳` its reach over fields.
- `⍸`, gather and amend: the filters, the masked stores, and the last
  of the finds.
- stepped slices: the `extra` table's columns.
- `⋈` for strings; `⍋` for the one sort.

The rule of thumb from the census: **a loop whose body is one `push`
is an operator waiting to be written; a loop whose body is one `if`
is a mask.**  Between them that is 200 of the 559, before any loop
that does two things is looked at.

---

# Second round: what is left, read on 2026-09-02

The five commits above landed everything §5 proposed.  This is the same
census taken again, on the source they left.

## What moved

| | before | after |
|---|---|---|
| `foreach` loops | 559 | 530 |
| `while` loops | 180 | 154 |
| `if #v > 0:` guards | 103 | 32 |
| linear finds over a name table | 20 | 6 |
| literal tables rebuilt per call | 17 | 8 (by design) |
| operators the compiler can write | `⍴ ⍳ ⧺` slices | those, and `¨ ⌿ ⍀ ⍸ ⍋ ⋈`, gather, amend, stepped slices, `∊` over arrays |

The loop count fell by 29 and the branch count barely moved.  That is
the honest shape of it: the operators went in, and the compiler's own
source used them at nine sites.  The remaining 530 loops are not
waiting on more operators, and the reason is worth writing down.

## Why the rest did not follow

Sorting the 530 by what stands in the way:

| what blocks it | loops | example |
|---|---|---|
| nothing -- a rewrite with what exists | ~25 | `foreach v := sv_names: self.snames.push(v)` is `self.snames ← sv_names` |
| **`¨` takes only a function's name** | ~30 | `out.push(sym_type(&a, &toks, src, e, seen))` -- the map carries context |
| the body is emission, not a value | ~47 | `foreach ci := caps: self.ir(ir.Ir.fsto, …)` |
| the body is several statements | ~326 | the checker's real work: read, test, record |
| a find that wants a hash, not an operator | 35 | `foreach i := 0…np: if self.text(…) = nm: return i` |
| a filter or an amend, convertible but cold | 17 | `if a.fns[fi].is_test: tests.push(fi)` |

**The one language gap left is the map that carries context.**  Half
the map-shaped loops (53 of 99) build an element from something
besides the element -- a table the loop indexes, a receiver, three
arguments the mapped function also needs.  In the full language that
is a `λ`; in the compiler's subset `¨` takes a function's name and
nothing else.

The interpreter already answers the smaller version of this:

```
let f := add(10)        // a partial application
f ¨ v                   // interpreter: [11, 12]
                        // compiler: 'f' is not a function this program defines
```

A partial application before `¨` and `⌿` is the one addition that
would pay: `sym_type(&a, &toks, src) ¨ types` is the shape of five
string-building loops in `symbols.ngpl` that `⋈` was written for and
cannot reach, and of the `self.lam_pt(lt) ¨ (argc…np)` family in the
checker.  It is a lowering change -- the each and fold loops call
through the box, as `lower_lcall` already does -- not a new operator.

## What can be done today, without touching the language

1. **The nine scope restores** (`check.ngpl:3492–3510`): the arrays are
   cleared and refilled from a saved slice, which is
   `self.snames ← sv_names` -- a field takes a plain array.  Nine
   loops, and nine `← []` lines with them.
2. **Append-many**: `x ← x ⧺ y` works for a local and for a field
   (checked).  `self.a.lte.push(pt)` per element, the two `rodata`
   byte loops, comptime's two pool copies, `strs0` -- about a dozen.
3. **Sub-range copies**: `rem.push(pts9[j])` over `argc…np` is
   `rem ← rem ⧺ pts9[argc…np]`; four sites in the checker.
4. **The eight filters** are `⍸` and a gather once the predicate is a
   named function: `tests ← ⍸ (ast.is_test ¨ a.fns)`.
5. **The identity array** `foreach i := 0…nrt: rt_order.push(i)` is
   `⍸ (nrt ⍴ true)` today; a monadic `⍳ n` would say it better, and is
   the only other operator worth adding.
6. **Six name-table walks** are left (`lower.ngpl:158` over `a.fns`,
   the parser's `mel`, `mtab.names`, `toks.strs`, the checker's
   `mnames` and `mel`); `names.Names` answers all of them.

## What is not an array operation and should stay a loop

The 326 multi-statement bodies and the 47 emission loops are the
compiler doing its work: reading a node, testing it, recording what it
found; or writing one instruction per element into the emitter.  An
`¨` over a function that mutates the emitter would say less, not more,
and the language has no reason to grow an each-for-effect when
`foreach` is exactly that.

Nor are the 35 finds: a walk down a table is the wrong algorithm, not
the wrong spelling, and the answer to the hot ones was a hash table,
not an operator.

## The measurements

Native self-compile 0.99 s (0.94 s before the operators went in, so
about 5% -- the operator forms allocate an array where the loop
allocated none, and the new runtime routine is in every image).
Interpreted, as the bootstrap's stage 1 runs it, 1466 s against 1373 s
before -- the same effect, magnified by the interpreter's per-node
cost, and a reminder that these operators are for what the source
says, not for what it costs.  Every commit held the fixed point and
compiled all 100 conformance programs to the same bytes.

