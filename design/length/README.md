# How Many, and How Much: `#` and `@sizeof`

## The Question

`.sizeof` answered two questions in one word.

On an array it answered a **count** — three elements — and on a struct
it answered a **size in memory** — sixteen bytes.  The answer told you
which one you had got by the unit it carried, `ptrdiff` for one and
`byte` for the other, which is a thing a reader has to know rather than
a thing the source says.

`@sizeof` was split down the middle in the same place, and its own code
said so: *"A written type asks how much storage it occupies; a value
asks how many elements it holds."*  So `@sizeof(i64)` was 8 bytes and
`@sizeof(someArray)` was an element count, and `@sizeof` of a
*dynamically sized* array was refused outright, because its length is
not part of its type — a refusal that only makes sense if the question
was about the length, which for a size in memory it is not.

And a `byte[]` hid all of it, since there the count and the memory are
the same number.

## The Decision

Two questions, two words.

- **`#` counts.**  How many things are in an array, a matrix, a string,
  a tuple.
- **`@sizeof` measures.**  How much memory something takes, in bytes,
  for anything at all — a scalar, a fixed array, a dynamic one, a
  string, a struct.

`.sizeof` is gone.  The refusal names both replacements, since a reader
who wrote it meant one of them.

## Why `#`

It was free.  The language uses `//` and `/* */` for comments, so `#`
was not lexed at all, and no other glyph was displaced to make room.

Prefix, because it asks a question about what follows rather than
combining two things, and it binds like the other prefix operators —
tighter than anything that joins, so `#a + 1` is one more than the
length.

## The Outer Dimension

A matrix answers how many rows it has, not how wide they are.  That is
the one number every container has whatever it holds, and it is the
number that indexes it: `#m` is the bound for the first subscript, as
`#row` is the bound for the second.  APL's `≢` answers the same way.

This is also why `#` is **not** threaded over a container of
containers, though every other unary operator here is.  Threading
applies where a value is deeper than the operator asked for; `#` asks
for a container, and a container of containers is still one container,
so there is nothing deeper than what it asked for and nothing to take
apart.  Marking it listable would change nothing — which is the
argument for not marking it.

The case that shows the difference is a vector of strings:

```
let words : str[] = ["ab", "cde"]

#words          // 2 — how many strings
#words[0]       // 2 — how long the first one is
```

Threading would have made `#words` be `[2, 3]`, and then a matrix would
have answered its row widths instead of its row count.  One of the two
had to give, and the outer dimension is the one worth keeping: it is
the answer every container has.

## What `@sizeof` Gained

Answering memory for everything means it answers for a *dynamic* array
too, which it used to refuse.  The length is not in the type, but the
memory is a fact about the value, and a value is what it was given.
That refusal existed only because the question was really about the
length.

Its old split had one visible consequence worth recording: the static
checker stands a declared type in for a local so that `@typeof` and
friends can be answered before anything runs, and a fixed array's
declaration keeps its shape in the brackets rather than in the
annotation — `let a : i32[3] = 0` states `i32`.  Standing for that
value with a single `i32` answered what one of its numbers occupies
rather than what the array does.  Under the old meaning the two
disagreed in *units* and the assertion was quietly left to run; under
the new one they agree in units and disagree in value, which would have
been a wrong answer rather than no answer.  So an allocation is now
left alone by the checker, which is what it always meant to be.

## An Array Is Not Made From One Value

Found while writing this and fixed with it, since it is the same
question about the same declarations.

`let f : i32[4] = 0` filled the array at a function's scope and was
refused at a global one, with a message about `i32` not being an array
type — the global path measured the allocated array against the
annotation, and a fixed array's annotation is only its *element* type,
the shape being in the brackets.  So no fixed-size array could be
declared at global scope at all, not even from a literal.

Both halves are settled the same way.  A scalar where an array goes is
a type error, whatever the type says the array should be, so the fill
is refused at both scopes; making many of one thing is what `⍴` is for,
and writing it leaves the making visible at the definition.  And the
global path now skips the coercion for an allocation exactly as the
local one does, so every form that works in a function works at the top
level.

## Comparison with Other Languages

| Language | Length | Memory |
|----------|--------|--------|
| C | `sizeof(a)/sizeof(a[0])` | `sizeof` |
| C++ | `.size()` | `sizeof` |
| Rust | `.len()` | `size_of` |
| Zig | `.len` | `@sizeOf` |
| Python | `len(x)` | `sys.getsizeof` |
| APL, BQN | `≢` | — |
| NGPL | `#` | `@sizeof` |

C is the one that shares a word between them, and it is also the one
where getting an array's length is a division that stops working the
moment the array is passed to a function.  Everything else separates
them; this now does too.

## Status

Implemented: `#` on an array, a matrix, a string and a tuple, carrying
`ptrdiff` (or `byte` for a byte array) so a length can be used as an
index bound; `@sizeof` answering memory for everything, including a
dynamic array; `.sizeof` removed, with a refusal that names both.
