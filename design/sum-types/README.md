# Sum Types

## The Question

A sum type holds a value of exactly one of several alternatives.  The
language already has product types (`struct`) and a `match` statement
that dispatches on the shape of optionals and results.  What it does
not have is a way to say "this is one of these".

The question is how a program should write that down.

## Considered

### Extend `enum` with payloads

```
enum Shape:
    point
    circle(r : f64)
    rect(w : f64, h : f64)
```

The route Rust, Swift, and the ML family take.  Today's payload-free
enum becomes the degenerate case, so nothing existing breaks, and the
declaration gives every alternative a name of its own whether or not
it carries data.

Against it: it makes `enum` two things at once — a set of named integer
constants, which is what the language uses it for today and what
`@flag` builds on, and a tagged union.  A program reading `enum` no
longer knows which it is looking at until it reaches the alternatives.

### A separate keyword

```
variant Shape:
    circle(r : f64)
    rect(w : f64, h : f64)
```

Keeps `enum` strictly integer-valued.  Against it: two constructs where
the payload-free case is expressible in both, and no rule to say which
a program should reach for.

### A sum of named types  — chosen

```
struct Circle:
    r : f64
struct Rect:
    w : f64
    h : f64

type Shape = Circle | Rect
```

The alternatives are types that already exist and are named, defined,
and usable on their own.  The sum composes them rather than declaring
new things inside itself.

This reuses `type`, which already names one type in terms of another;
`A | B` extends that from one target to a choice of them.  It adds no
keyword.

Against it: an alternative has no name separate from its type, so two
alternatives cannot share a type — `type T = i32 | i32` is not a
two-alternative type, it is a mistake, and is rejected as one.  Where a
program wants two alternatives of the same shape it declares two
structs.  This is the cost of the choice and is accepted.

## The Tag

A value carries which alternative it is.  The alternatives are distinct
named types, so the value's own type is the tag — there is no separate
discriminant for the program to keep in step with the data, and no way
for the two to disagree.

The interpreter therefore stores nothing extra: a value of a sum type
is the alternative's value, and `match` reads its type.  A compiler is
expected to lay this out as a discriminant beside the payload; the
language does not promise a layout, which leaves the compiler free to
use a spare bit pattern in the payload instead where one exists.

## Untagged Unions

Deliberately not provided.  An untagged union has no way to say which
alternative is live, so nothing can check a `match` over it and every
read is a claim the compiler cannot verify.  That belongs with the
insecure mode, which does not exist yet.  Until it does, there is no
`@repr(union)`.

Note that when it arrives it need not be a second construct: dropping
the tag is a representation, and `@repr` is where representations are
already written.  Rust needs `enum` and `union` to be separate because
the safety difference is baked into the declaration; here it would
follow from one attribute.

## Untyped Numbers

`type Scalar = i32 | f64` and the call `kind_of(5)` pose a question the
struct case does not: `5` is an untyped integer and is not, yet, either
alternative.

The rule adopted mirrors what an untyped number already does at a
parameter of a plain type — it settles on the type it is being asked
for.  Where more than one alternative could hold it, no choice is made
and the program is told to say which it meant:

```
type Widths = i32 | i64
width_kind(5)    // error: could be i32 or i64; write the type meant
```

An untyped integer only considers integer alternatives and an untyped
float only float ones, so `Scalar` is unambiguous while `Widths` is
not.

## Status

Implemented: declaration, the admitted-value check at bindings and
parameters, `match` by alternative, and static checks for a repeated
alternative, an alternative that does not belong to the type, a
non-type pattern, and a missing alternative.

Alternatives may be structs, built-in types, or enums.  Enums became
usable as type names after this was first written.

Not implemented:

- Exhaustiveness where the subject is not a parameter.  A parameter is
  where a type is written down; a name bound from an expression carries
  the alternative's own type, and nothing is claimed about it.
- Anonymous sums in a signature, as in `fn f(x : i32 | str)`.
- Generic alternatives.
