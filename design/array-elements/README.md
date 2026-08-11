# One Type and One Unit for Everything an Array Holds

## The Question

An array's type is supposed to say what it holds.  It barely did:

```
let a : mut i32[] = [1, 2]
let s : str[] = ["x", "y"]
a ← s                      // accepted; a now holds strings
a.push("smuggled")         // accepted
let b : mut i32 = 1
b ← 5000000000i64          // accepted; b is now an i64
```

Ten ways in were found and every one of them was open.  Underneath were
two structural gaps, and the interesting thing is that they are the
same gap seen twice.

**Nothing remembered a declaration.**  The environment stored values
and nothing else.  The type and the unit a definition wrote down were
used once and dropped, so every later check re-derived what a name
holds from whatever it happened to hold at that moment.  A declaration
therefore lasted exactly one statement: after the first assignment the
name answered for its new value rather than for what it was declared
to be, and since the check for an array asked a routine that has no
opinion about array types, it was not even asked.

**A unit attached to the container.**  `let d ¤meter : i64[] = [1, 2]`
built a measured *array*, which is not a thing.  It could not be
indexed — `d[0]` failed outright, because nothing reads an element out
of a unit — and converting one raised about an internal object.  There
was no way to declare the thing anyone actually wants, an array of
measured numbers: writing the elements measured and the type plain was
refused, and there was no syntax that said it.

## What Decided the Design

**A unit measures a number, and a container is not one.**  So where a
declaration states an array type and a unit, the unit reaches every
element however deep it sits.  That is not a new rule — it is the
sentence the manual already writes about the element *type*, applied
to the other half of what a declaration says.

**A declaration is the pair (type, unit).**  Every declaration site
already held both halves: a definition, a parameter, a return type.
Once that is the unit of currency, the two spellings

```
let d ¤meter : i64[] = [1, 2]
let d : i64 ¤meter[] = [1, 2]
```

are not two features to keep in step.  They parse into the same pair,
so there is no difference left to maintain and nothing to test but the
absence of one.

## Where the Unit Lives

**Not in the type string.**  Types are plain strings throughout the
interpreter, and a unit is a *formula* — `m÷s`, `√…`, `¤"widgets"` —
so encoding it would mean re-parsing it in every place that takes a
type apart: the array-type regex, alias resolution, validity checks,
the generic machinery, the bootstrap checks, and every error message
that quotes a type.  The one thing it would buy is a unit inside a
tuple or a struct field, which is exactly the question deferred to the
sum-and-product task.

**On the value.**  An array already remembers what type its elements
are; it now remembers what they measure, in the same place and read the
same way.  Where the array was not told, it reads the unit off its
first element, which makes every array built by slicing, joining,
reshaping or threading answer correctly without each of those places
having to say so.

## Why Before the Brackets

`i64 ¤meter[2,3]` puts the unit where the element type is, because it
is the element's unit.  The brackets that follow are the array's shape,
and the reading is the same at any rank: three dimensions or none, the
unit is still each number's.

A return type could already state a unit *after* the brackets.  Both
are accepted, and writing both is refused.

## What a Definition Says and What an Assignment May Not

A definition may measure a bare number, because the definition is what
says what the number counts:

```
let d ¤meter : i64[] = [1, 2]   // [1 m, 2 m]
```

An assignment says nothing, so what it stores has to arrive measured —
otherwise the measure would be invented for it.  That rule already
existed for a scalar; it now holds for an array, and it is the reason a
declaration has to be remembered rather than inferred from the value.

## What Is Refused, and Where

Every way into an array asks one routine, so the answers cannot drift:
a subscript, a `push`, an `insert`, a whole-array assignment, an
argument, a lent array, and a return.  A row of a matrix is one of the
things the matrix holds, so it is measured like any element — which,
because the measuring runs through the same coercion a declaration
uses, checks the row's length along with its kind.

A width still converts, with the range check, exactly as it does at a
definition.  That was a choice: the alternative — a stated width must
match exactly — is arguably the truer reading of "one type", but it is
a different question from homogeneity, it changes scalar assignment as
well, and it deserves its own pass.

Two arrays join only where they hold the same thing.  Taking the left
operand's element type and the right operand's values built an array
whose type was a lie about half of it, and every later write to that
array believed the lie.  The manual sanctioned this and is corrected
with it.

## Left for the Sum and Product Types

A unit written inside a tuple element or a type alias is refused *by
name* rather than left to fail on the glyph.  There it would have to
belong to the type itself rather than to a binding or to what an array
holds — and where the members are numeric and unmeasured the answer
may well be that the variable may state it after all.  That is the next
task, and the refusal is where it will start.

## Status

Implemented: declarations are remembered and every assignment is
measured against one; a unit reaches the elements of an array at a
definition, a parameter and a return; the second spelling; homogeneous
literals; and the element checks on every way in.

Found while doing it, and not fixed here: four test files —
`test_units`, `test_float`, `test_power`, `test_roots` — call their
tests from `main` rather than marking them `@test`, so the suite runs
them with `--test`, finds nothing, and reports them green.  Eighty-three
test functions do not run, and `test_units.ngpl` fails when it is run.
