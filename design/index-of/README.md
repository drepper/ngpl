# Where Something Is: `⍳`

## The Question

Looking for something in an array or a string is one of the things
every program does, and the language had no way to write it.  A
program had to walk the container itself, counting as it went.

What had to be decided was the shape of it: an operator or a method,
whether one spelling serves both an array and a string, what it
answers when what is looked for is not there, and what that answer
carries.

## Considered

### A method — `v.find(x)`, `s.find(t)`

What C++, Python, and Rust do.  It reads well and it is discoverable,
and against it is that text and arrays end up with separate spellings
which have to be learned separately — `strchr`, `memchr`, `.find`,
`.position` — even though a program means the same thing by all of
them.

### An operator — chosen

`⍳` (U+2373 APL FUNCTIONAL SYMBOL IOTA), which is what APL uses for
exactly this.  One glyph serves an array and a string, so a program
that has learned it for one has learned it for the other, and there is
no separate `.find` for text.

The left operand is the container, the right is what is looked for.
That order is APL's, and it is also the order the sentence goes in:
*where in `v` is `20`*.

## What It Answers

Counted from zero, and the first of several.

### An optional, not a sentinel

APL answers with the length of the container — a position one past the
end, which the program has to remember to compare against.  Everyone
else has a sentinel of their own: a null pointer, `npos`, `-1`.

```
v ⍳ 99                          /* ∅ */
(v ⍳ 99) ?? ⁻1                  /* the sentinel, where one is wanted */
```

A position that is not in the container is not a number to invent.
The optional says so in the type, so a program that forgets to ask is
refused rather than reading past the end — which is the whole of what
the language is for.  Rust reached the same answer with `None`, and a
program that does want a sentinel writes `??` and has said so.

### An index, not a count

The answer carries the unit an index of that container carries —
`ptrdiff`, or `byte` for a `byte[]` — so what comes back can be used to
look with rather than having to be re-annotated:

```
let i ¤ptrdiff : i64 = (v ⍳ 20) ?? 0
v[i]
```

The unit is on the answer and not on what is looked for.  An element
of a `byte[]` is a byte and not a count of bytes, so `b ⍳ 98` is
written without one; this is the same distinction the language already
draws between a `byte` and `¤byte`, and it costs a reader nothing that
`==` does not already cost them.

## Grouping

The same level as `⌈` and `⌊`: looser than every arithmetic and
bitwise operator, tighter than the comparisons and `…`.

What is looked for is often computed and what comes back is usually
asked about rather than combined, so this is the grouping that needs no
parentheses in either direction:

```
v ⍳ n + 10          // what is looked for is the sum
```

## What It Refuses

The operator is one of the places a mistake can be caught for free, so
it refuses rather than answering something a program might believe.

- **A container it cannot look in.**  A range is a pair of ends, not
  something to search, and the refusal names it as a range rather than
  as the type of its ends.
- **A unit that does not belong.**  An element is compared the way `==`
  compares it, by going through the same door, so `v ⍳ 20¤byte` is
  refused where it is written rather than quietly matching nothing.
  An operator that did its own comparing would have been a second
  place for the unit rules to live, and the two would have drifted.
- **More than one dimension.**  A position in a matrix is not one
  number, so there is nothing honest to answer; a row of it is searched
  on its own.
- **A string searched for a number**, since a number is not a part of
  one.  In a string what is looked for is a character or a run of
  them, and a run is where it starts.

Searching for an element of a type the container does not hold is
*not* refused: it answers `∅`, because that is what `==` answers
between two values of unrelated types everywhere else in the language.

## Comparison with Other Languages

| Language | Where something is | When it is not there |
|----------|--------------------|----------------------|
| APL | `⍳` | the length of the container |
| C | `strchr`, `memchr` | a null pointer |
| C++ | `.find()` | `npos` |
| Python | `.index()` / `.find()` | an exception / `-1` |
| Rust | `.position()`, `.find()` | `None` |
| NGPL | `⍳` | `∅` |

The glyph is APL's and the answer is Rust's.

## Status

Implemented: on arrays, on slices of them, and on strings, for an
element, a character, or a run of characters; answering an optional
index carrying the container's index unit; settled at compile time
where the container and what is looked for both are.

APL's monadic `⍳n` — the first *n* numbers — is not provided.  The
language writes that as a range, `0…n`, which says the same thing in
the notation it already has for it.
