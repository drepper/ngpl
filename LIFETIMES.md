# Borrows That Come Back, and Lifetimes That End at the Last Use

A design for object lifetime and access in NGPL: how a function may
answer a reference into what it was lent, and how the life of a value
ends when the program is finished with it rather than when a block
closes.  The second half of this document is what was built of it on
the branch `feat/borrow-returns`, and how far that reaches.

## 1. What the language has today

Three things are already in place, and the design builds on all of
them rather than replacing any.

**Borrows on parameters.**  A parameter is `&T` or `&mut T`, the
argument is written `&x`, and a callee that writes through a `&` is
refused.  A call may not lend one binding to two `&mut` parameters.  A
borrow "begins and ends inside the call" (spec, *Borrows That Nothing
Can Observe*) — which is exactly the sentence this design has to
change, because a borrow that is answered does not end inside the call.

**Holds.**  While a walk or an iterator borrows a binding, the checker
holds it: `HOLD_READ` lets the name be read and not changed,
`HOLD_NONE` makes the name reach nothing at all.  A write through a
held name draws 2400; a read through one held `HOLD_NONE` draws 2401.
The machinery is `sheld`, `hold()`, `base_slot()` in `src/check.ngpl`.

**Lifetimes.**  The checker numbers statements as it reads them and
records, for every binding, the statement that declares it (`born`)
and the statement that last uses it (`last`).  A binding handed as a
`&mut` to something that could keep it is marked `escapes`, and its
lifetime runs to the end of the scope instead.  `--log=json` writes one
line per binding.  Nothing is done with the answer: no hold ends at a
last use, and nothing is given back to the allocator (RT_FREE exists
and is called from one place, when a push copies an array out of a
block it has outgrown).

## 2. The defect that motivates the design

```
struct Bag:
    items : i64[]

impl Bag:
    fn view(&self) → i64[]:
        self.items

let b : mut Bag = Bag{items: [1, 2, 3]}
let v : mut i64[] = b.view()
v.push(4)
std.println("{} {}", #b.items, #v)         // 4 4 -- in both implementations
```

The spec says a by-value result is a copy and that the copy is elided
only "where the difference cannot be seen".  Here it can be seen: `v`
is the bag's own array under another name, and pushing to it grows the
bag.  The function is not wrong — handing out a view of a field is
exactly what such a method is for — but it has no way to *say* that
what it answers is a view, so the language cannot hold the caller to
the terms of one.  The same gap stops the honest version from being
written at all: `→ &i64[]` is refused with "a borrow is written on a
parameter, not here".

So the first requirement is expressibility: a function that takes a
reference must be able to answer a reference to the same object, or to
a part of it, and the answer must be tied to the thing it came from so
that the caller is held to it.  The second requirement is that the
holds — and the lives of the values behind them — end when the program
is finished with them, which is a question about the program's reads
and not about where its blocks close.

## 3. The model

### 3.1 Owners and borrows

Every value has one **owner**: the binding, field, or element that
holds it.  A **borrow** is a claim on an owner.  While a borrow is
live, the owner is held: for reading under a shared borrow, not at all
under a mutable one.  This is the language's existing rule for walks,
stated once for everything.

A borrow has a **lifetime**: from the statement that takes it to the
statement that last uses it.  A binding has a lifetime the same way.
Both are worked out by the compiler from the program's reads, and
neither is the extent of a block.  The one exception is a value that
*escapes* — is handed to something that may keep it — whose lifetime
runs to the end of its scope because nothing closer can be seen.

### 3.2 A borrow that comes back

A function may answer a borrow.  Its return type says so and says
where the borrow comes from:

```
fn items(b : &Bag) → &i64[] |b|:
    b.items
```

`|b|` names the **origin**: the parameter the answer reaches into.  It
is the capture list's notation, and it means what a capture list
means — what this reaches from outside itself — so the language
acquires no new bracket.  It may be left off when there is exactly one
borrowed parameter, or when the only one is `&self`:

```
impl Bag:
    fn items(&self) → &i64[]:              // origin: self
        self.items

fn longer(a : &Bag, b : &Bag) → &i64[] |a, b|:
    if #a.items > #b.items: a.items else: b.items
```

Two or more origins say the answer may come from any of them, and the
caller is held to all of them.  An answer that may change what it
reaches is `→ &mut T`, and each of its origins must be `&mut`.

**In the body**, what is answered must be **rooted** in an origin: the
origin itself, a field reached from it, an element of it whose type is
something borrowable, or what a borrow-returning call answers when
rooted in it.  Anything else is refused, because the borrow would
point at something that is gone when the function returns:

```
fn fresh(b : &Bag) → &i64[] |b|:
    let t : i64[] = [1]
    t

error 2432: 'fresh' answers a borrow of 'b', but this answers 't', which is
           the function's own and is gone when it returns
```

**At the call**, the result is a borrow of whichever caller bindings
fed the origins, and those bindings are held — for reading under
`&T`, not at all under `&mut T` — from the call to the result's last
use:

```
let b : mut Bag = Bag{items: [1, 2, 3]}
let v := b.items()                 // v : &i64[], a borrow of b
std.println("{}", #v)              // v's last use: the hold on b ends here
b.items.push(4)                    // fine
```

and, with the uses the other way round:

```
let v := b.items()
b.items.push(4)
std.println("{}", #v)

error 2430: 'b' is lent out for reading to 'v' until line 3 and cannot be
           changed before then
```

The message names the borrow and the line where the hold ends, which
is the thing a reader cannot see otherwise.  A hold that ends at a last
use is what makes the first form legal: under a lexical rule `b` would
be locked to the end of the block, and every function that hands out a
view would make its receiver unusable for the rest of the caller.

**A borrowed result may not outlive the function that holds it.**  It
cannot be pushed into a container, stored in a field, assigned to a
global, or captured by a lambda; and it can be returned only from a
function whose own return type is a borrow with the right origin,
which is what makes the chain composable:

```
fn first_items(bs : &Bag[]) → &i64[] |bs|:
    bs[0].items()                              // a borrow of an element of bs

let x : mut i64[][] = []
x.push(b.items())

error 2433: what 'items' answers is a borrow of 'b' and lives only as long
           as 'b' is held; 'x' may outlive that
```

### 3.3 Where a lifetime ends

A binding's lifetime ends at its **last use**.  Three things follow,
and they are the substance of "not purely syntactically":

1.  **Holds end there.**  A borrow's origin is released at the borrow's
    last use, as above.
2.  **Resources are released there.**  A file or directory bound to a
    name is closed after the statement that last reads the name, not
    when the enclosing block ends.  The spec's *Resource Lifetime and
    Scope* becomes the worst case rather than the rule: a resource
    that escapes — is passed on, stored, returned — still lives to the
    end of its scope, because nothing closer can be seen.
3.  **Memory is reclaimed there.**  An owning binding whose value never
    escapes is given back to the allocator after its last use.  This
    is the `[ ]` item in TODO-compiler.md about RT_FREE, and the
    lifetime the checker computes is, as that item says, the beginning
    of it.

The rule that keeps the three sound is the one the checker already
applies: **a use that hands the value to something that may keep it is
not a last use.**  A `&mut` handed to an impure callee, a by-value
argument to anything, a push, a store, a return, a capture — each of
these makes the binding escape, and an escaping binding's lifetime is
its scope.  Reclaiming is therefore only ever done for a value that
the function made itself and showed to nothing that could hold it.

A loop is one statement for this purpose.  A name read anywhere inside
a loop body is in use until the loop's last statement, because the
read at the second turn comes after the write at the first.

### 3.4 What is deliberately not in the model

- **No lifetime variables.**  Rust names lifetimes so that a signature
  can relate several of them; NGPL relates a result to its origins by
  naming the origins, which is the one relation a function in this
  language needs to state.  A borrow stored in a struct — which is
  what would need a named lifetime — is refused instead (2433).
- **No borrows of scalars.**  A `&i64` travels by value today and goes
  on doing so; `→ &T` is for the types `&T` parameters take: arrays,
  structs, dictionaries, matrices.
- **No reclaim of anything shared.**  A value reached through two
  names, or handed to anything, lives to its scope's end.  The
  reclaim is a whitelist and stays one.

### 3.5 Diagnostics

| code | said when |
|---|---|
| 2430 | a held origin is changed, or mutably borrowed, before the borrow's last use |
| 2431 | a held origin is read while lent `&mut` |
| 2432 | a borrow-returning function answers something not rooted in an origin |
| 2433 | a borrowed result is stored, returned plain, or captured — would outlive its origin |
| 2434 | `→ &mut T` whose origin is not `&mut`, or a non-borrowed parameter named as an origin |
| 2435 | an origin list is needed (two or more borrowed parameters) and none was written |
| 2436 | a borrowed result is bound by a `let` that names a plain type |

## 4. The extended syntax

```
fn name(p : &T, …) → &U |p, …|:          -- answers a shared borrow of p
fn name(p : &mut T, …) → &mut U |p, …|:  -- answers a mutable one
fn name(&self) → &U:                      -- origin elided: self
fn name(p : &T) → &U:                     -- origin elided: the one borrowed parameter
```

The result type of a call to such a function is `&U` or `&mut U`.  A
`let` that binds it writes no type, or writes `&U`; writing `U` asks
for a copy, which is a different thing and is refused (2436) so that a
copy is never made by accident where a borrow was handed over.

## 5. What was built

### 5.1 Both implementations

- **Without the `&`, the answer is a copy.**  A plain-typed answer that
  is not the function's own — a field, an element, a parameter, a
  global, or a binding born from one of those — is copied on the way
  out; a value born fresh in the function (a literal, a join, a slice,
  a call's answer, a reshape of a scalar) is moved.  Arrays are copied
  by `ALEN`+`ACYC` as an elided argument copy already is, structs by a
  field-for-field `SNEW`; the interpreter deep-copies the container.
  The compiler's own source incurs two copies, both in the comptime
  evaluator, and the self-compile is unchanged.  This is the other
  half of the defect in section 2: the two signatures now say two
  different things and each is held to its word.

- The return-type syntax above, including origin elision and the
  refusals 2434 and 2435.
- The body check 2432: the answer is rooted in an origin, through
  fields, elements and borrow-returning calls.
- The call-site hold: the origin bindings are lent to the result until
  the result's last use, computed by a pre-scan of the function body
  that numbers statements as the checker does and treats a loop as one
  statement.  2430 and 2431 on a write or read in between.
- 2433 where a borrowed result is pushed into an array, written into
  a struct literal's field, bound whole to another name, or answered
  plain by a function that does not itself answer a borrow.  A capture
  of one is already refused, since a capture is a scalar.  A store into
  a global is not checked yet.
- `--log=json` reports each lend as it is taken: `{"decision": "lend",
  "origin": "b", "to": "v", "until": 13}`, `until` being the line the
  lend runs to.

### 5.2 The interpreter

The interpreter has no static pass, so it does the same with what it
has: the returned object must be reachable from an origin argument's
object graph (checked at return, by identity), and the origin names
are frozen `"lent"` in `_frozen_vars` from the call to the statement
of the result's last use in its block, found by a scan of the block's
AST that is cached per block.  Resources are destroyed after the
statement of their last use when the name is confined — never handed
whole to a call, kept, returned, or asked something whose answer is
kept, since an iterator over a directory reaches back into it — which
is observable in descriptor numbers and is tested that way
(`tests/test_borrow_returns.ngpl`).

### 5.3 The compiler

The compiled subset carries the borrow as what a `&T` parameter is
already: the pointer to the object, so a `→ &T` costs nothing to
return.  The last use is read off the function's tokens before the
body is checked, through a small open-addressed table (a walk per
token was more than the bootstrap's interpreted stage could afford),
and a loop is one statement: on entering one, every lend whose end
lies inside it is stretched to the loop's end.

Reclaim is implemented for the case that is provably safe — an array
of scalars that a binding made from a literal or a join, read only
where a packed array could serve (the checker's `kuse = ksafe`), and
never handed anywhere — and reuses the give-back sequence a walk
already emits on all six targets (`IR_GIVEBACK` on the element block;
the descriptor is left, as the walk leaves it).  The decision is
settled at the function's end, after the packing analysis, because an
array the packing lays out in the frame has no block to give back:
that was the first attempt's mistake, and thirteen conformance
programs found it.  It is logged as `{"decision": "reclaim", "name":
…, "at": …}`.  The bootstrap's self-compile is 0.57 s against
0.51 s before, the difference being the per-statement bookkeeping;
the first version was 0.81 s, and the whole of that came from the
last-use scan reading each method from its `tok_lo`, which for a
method is where the impl block began rather than where the method
did -- 6.5 million tokens for 1205 functions.  The scan now starts at
the name.  `tok_lo` itself is left as it was, and noted in
TODO-compiler.md, since it is also what the bill of materials hashes.

### 5.4 Not built, and why

- Reclaim of strings, structs, dictionaries and arrays of them: each
  needs its own drop routine, and a struct's needs to know which
  fields own what.  The decision machinery is the same; only the
  routines are missing.  A slice or a reshape is left alone too, since
  either may share storage with what it was cut from.
- Releasing a resource at its last use in the *compiled* subset: the
  subset has no resources.
- A borrow of an element of an array of scalars (`&v[i]` as `&i64`):
  scalars travel by value, see 3.4.
- `while` bindings and `match` arms as borrow sites: the pre-scan
  treats their names as any other, but no test pins them.
