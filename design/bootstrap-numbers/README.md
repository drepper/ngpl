# No Arbitrary-Precision Value in the Bootstrap

## The Question

`int` and `float` are the arbitrary-precision types, and belong to the
full language.  The bootstrap refused a declaration naming one from the
start — a variable, a parameter, a return type, a field, an alias.

That turned out to refuse the words while allowing the thing.  A value
could still reach an arbitrary-precision type without anyone writing
its name:

```
let n := 5              // an int, by inference
let a := [1, 2, 3]      // an array of int
let t := (1, "two")     // a tuple holding an int
2 ↑ 200                 // an int, computed
```

The specification blessed the first of these explicitly: an
unannotated binding settles on `int`, and "the inferred form stays
available in the bootstrap; only *writing* `int` is refused there".

So the question was what the bootstrap should do with a number that has
not settled on anything, given that it has nothing for one to settle
on.

## Considered

Three answers, in increasing strictness.

### Require the result to fit a sized type

Untyped stays untyped while folding; a value that is materialized must
fit *some* sized type.  `2 ↑ 200` is refused for needing more bits than
any type has; `let n := 5` is untouched.

The smallest change, and it removes the values that genuinely cannot be
represented.  Against it: `let n := 5` still produces a binding whose
type is `int`, so the language would still be saying it has a type it
does not have.

### Settle on a default sized type

`let n := 5` gives an `i64`, `let f := 1.5` an `f64`, as Go does with
its untyped constants.  Nothing is ever an `int`, and no source has to
change.

Against it: the default is invented rather than written.  A program
that meant `u8` gets `i64` and finds out later, and `1 « 63` becomes an
overflow where it is exact today — silently, because the type that
overflowed was one nobody wrote.

### Require the type to be written — chosen

Nothing without a stated type may hold a number.  A binding whose value
would settle on `int` or `float` is refused, and the diagnostic names
the type to write.

This is the strictest of the three and the only one under which the
absence of `int` is true rather than nearly true.  It costs the most:
something over four hundred bindings in the project's own test suite
had to say what they are.  That cost is also the argument for it —
every one of those was a place where a program was relying on a type
the bootstrap does not implement, and a handful of them turned out to
be relying on the wrong one.  SHA-256's round constants and message
schedule are `u32`, and what `std.bytes` hands back is `byte[]`; both
had been running as whatever the untyped elements happened to be.

## Where a Value Can Arrive Without a Type

The rule is one check, applied wherever a value is kept or handed on.
Four places, and they are not the same question:

| Site | How the program answers |
|---|---|
| a binding | `let n : i64 = 5` |
| an array | `let a : i64[] = […]`, or `[1i64, 2, 3]` |
| a tuple | `(1i64, "two")` |
| an argument | the parameter's declared type, or a value a type could hold |

**An array** may be answered from either side.  A binding can say what
the array is, or one element can say what its numbers are and the rest
take it — which is the rule for literals applied within the array.
Making the second form true meant an array literal settling its
elements when it is built, rather than leaving each as it was written.

The type it asks for is written the way a program would write it: a
dimension is a comma inside one pair of brackets, so an array of arrays
is `i64[,]` and not `i64[][]`.

**A tuple** answers the same two ways, with one difference: its
elements are types of their own, so one of them stating a width says
nothing about the others.  Either the binding states the tuple's type
or every number states its own.

There was no tuple type when this rule arrived, so for a while the
diagnostic asked for the suffixes and said why: a tuple's type is
written element by element, and the language had no syntax for the
sequence.  Being unable to say what a value is turned out to be the
larger gap, and the type was added -- `(i64, str)`, written the way the
value is.  See [The Tuple Type](../tuple-type/README.md).

The corollary is that a tuple the standard library hands back must
arrive sized, since nothing the program could write would say what its
numbers are.  `std.callstack()` gives `(str, i64, i64)`.

**An argument** to something that states no parameter type — a
standard-library call, or a function with an untyped parameter —
settles nothing either.  There the rule is the weaker one from the
first option above: the value must be a number some sized type could
hold.  Requiring a stated type would mean `std.println("{}", 5)` could
not be written, which is not a language anyone would use.

The bound is `u128` and `i127`, the widest sized types, not 64 bits.
The language has integer types of any width up to those, so a number
one of them could hold is a number that settles; only what none of them
could hold is arbitrary precision.

## What a Literal Still Is

Unaffected while it is being computed with.  A literal states no width,
takes the one it meets, and is exact until then:

```
let big : i64 = 1 « 40      // computed at full precision, then held
let q : u8 = p + 1 - 1      // the literals take u8
static_assert(2 ↑ 200 > 0)  // never a runtime value
```

The distinction that matters is between a value being computed and a
value being kept.  The bootstrap has no representation for the second
without a type; the first is the compiler's arithmetic and needs none.

## What the Change Uncovered

Two things had been hiding behind the old behaviour, and neither was
found by looking for it.

**A float literal did not give way to a sized operand.**  `f64 + 2.5`
answered `float` — the arbitrary-precision type — where `i64 + 2`
answers `i64`.  Integers were right because an untyped integer has a
width of its own, distinct from `int`; floats had no such marker, so
`float` was doing both jobs.  It now gives way, as the integer literal
does.

**A loop variable over untyped bounds was an `int`.**  That is why an
accumulator it was added to came out arbitrary-precision: `total ←
total + i` resolved to the wider of `i64` and `int`.  The loop variable
is now uncommitted rather than an int, so it settles at the first typed
thing it meets — which is also what lets it go on indexing an array,
since an index must be a literal or carry `ptrdiff`.

## Status

Implemented: the check at a binding (local and global), inside an array
literal, inside a tuple, and at an argument to something that states no
type.  A lambda's parameters and return type, which no declaration
check had reached, are refused like any others.

A global may now state a unit as a local could, which it has to be able
to do once every binding must name a type.

Not implemented: parameter types for the standard library, which would
let an argument settle rather than merely be measured.
