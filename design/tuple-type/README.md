# The Tuple Type

## The Question

Tuples were values without a type.  A program could build one, index
it, take one apart in a `foreach`, and hand one back from the standard
library — but nowhere could it write down what one *is*.  `@typeof`
answered `tuple` and stopped there.

That was liveable until the bootstrap stopped allowing values that had
settled on nothing.  Every other place a number could arrive had an
answer: a binding could state `i64`, an array `i64[]`.  A tuple had
none, so the rule had to be spelled differently for it — every number
inside carries a suffix — and the diagnostic had to explain that there
was no type to write instead of naming one.

A rule that cannot be satisfied the way the others are is a gap in the
language, not a rule.  So: what does a tuple's type look like?

## Considered

### `(i64, str)` — chosen

Written the way the value is.  `(1i64, "two")` has type `(i64, str)`.

This is what Rust, Swift, Python's typing, and the ML family all do,
for the reason that makes it obvious: a reader who can write the value
can write its type.  It is also the principle the language already
follows for arrays, where `[1, 2, 3]` has type `i64[]` — the brackets
of the value, with the element type in front.

### `tuple[i64, str]`

A named constructor with the elements as parameters.  Against it: the
name adds nothing a reader did not already know from the parentheses,
and it stops the type reading like the value.

### A named product type instead

`struct Pair: a : i64; b : str` already exists, and one could argue
that a tuple wanting a type is a struct that has not admitted it.

Against: a tuple's elements are positional, and there are places —
`std.callstack()`, `enumerate`, a fold's `(container, init)` — where
the language itself produces them.  Those need a type whatever the
advice to programmers is.

## What Follows From the Choice

- **Elements are types in their own right.**  Each may be anything a
  type may be, so `((i64, i64), str)`, `(i64[], str)`, and
  `(i64, str)[]` all mean what they look like.
- **The type may go wherever a type may go**: a binding, a parameter,
  a return type, a struct field, a type alias, a lambda parameter, an
  array's element type.
- **Stating the type settles the elements**, as it does at any other
  binding: in `let t : (u8, f64) = (200, 1.5)` the `200` is a `u8`.
- **A value is measured element by element.**  The count has to match,
  and each element has to be what its position says.
- **`int` and `float` are refused inside one**, as they are anywhere
  else a type is written in the bootstrap.

### One element is not a tuple

`(i64)` is `i64` — parentheses around a type are grouping, as they are
around an expression.  A tuple of one element would be a value with
nothing to distinguish it from the element it holds, so tuples start at
two.  Python needs `(x,)` to say otherwise because its parentheses are
not part of the tuple syntax; here they are, and there is nothing to
disambiguate.

## The Canonical Form

The type is rebuilt from what was parsed rather than kept as written,
so `(i64,str)` and `(i64, str)` are one string and compare equal.  Type
identity in this implementation is string identity — an alias resolves
to the text it names — so two spellings of one type had to become one
text.

## Status

Implemented: the type at every site a type is written, coercion element
by element, arity and element-type diagnostics, nesting in both
directions with arrays, and the bootstrap check reaching inside.

The diagnostic that asks a binding to name a type now writes a tuple
type out where the value is one, so the message that used to explain
the absence names `(i64, str)` instead.

`@typeof` answers with the type rather than with the word `tuple`, so a
value says about itself something a program could write down:

```
let t : (i64, str) = (1, "two")
@typeof(t)                      // (i64, str)
```

Comparing that against a type as *written* meant deciding what
`(i64, str)` is in an expression, where the parentheses already look
like a tuple literal.  It is the type: a name that names a type is that
type wherever it appears, and a parenthesized list of them is the tuple
type they describe.  A tuple with anything else in it is an ordinary
tuple, so the rule only takes over where every element is a type.

What that costs is a tuple *value* whose elements are all types, which
is no longer constructible.  Nothing can use one — there is no type of
types to hold it — and the thing it would have been written for is
exactly the comparison this enables.

## Taking One Apart

A definition may name the elements instead of the tuple:

```
let (a, b) := pair
let ((a, b), c) := nested
let (n, _) := pair
```

The syntax is the value's again — parentheses and names where the tuple
has parentheses and elements — so nesting needs no rule of its own, and
`_` means at a definition what it means everywhere else.

Three things were decided here rather than falling out:

- **`mut` reaches every name.**  It says how the definition binds
  rather than what any one element is, and a form that let each name
  differ would need a syntax nobody has asked for.
- **A repeated name is refused.**  `let (a, a) := pair` binds `a`
  twice, which cannot be what it means; a plain `let` that repeated a
  name would be refused too.
- **A stated type is the tuple's**, not a list of the elements'.  It
  settles the elements before they are named, so
  `let (a, b) : (u8, str) = (200, "x")` gives `a` a `u8` — the same
  thing the type does at a binding that names no elements.

A parameter takes one apart the same way, in the same shape:

```
fn first((a, b) : (i64, str)) → i64:
    a

fn sum_of_pair((a, b)) → i64:          // the type may be left off
    a + b
```

The argument is measured against the stated type before it is taken
apart, so the two failures a parameter can have — not a tuple, and the
wrong number of elements — are reported against the parameter rather
than against something inside the body.

A `match` arm names the elements the same way, for every pattern that
binds:

```
match maybe_pair():
    ∃((a, b)):
        a + b
    ∅:
        0
```

That one is where the shape earns its keep.  An arm already binds what
it matched; naming the elements of it is the same operation the other
two sites perform, so a reader who has met one has met all three, and
the implementation is one function called from three places.

This is a pattern in the sense that `match` has patterns, but it is not
the general one: a destructuring names elements and cannot ask about
them.  There is no `∃((a, 0))` matching a pair whose second element is
zero.  The language will want the general form eventually, and when it
arrives this should be a case of it rather than a separate feature.

Not implemented: destructuring in an assignment to names that already
exist — `(a, b) ← pair` — which is a question about what an assignment
target may be rather than about tuples.
