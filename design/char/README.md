# The Character Type

## The Question

Strings existed; characters did not.  A program could hold text and
print it, but there was no way to look at what it was made of — a
string could not be iterated, and nothing named one of its elements.

The question is what that element should be.  Three answers were
available, and the language's own commitments rule out two of them.

## Considered

### A byte

What C does, and what `foreach` over a `byte[]` already gives.  The
language mandates UTF-8 source and UTF-8 strings, so a byte is not a
character in any string that leaves ASCII: iterating `"héllo"` by byte
gives six elements for five characters, and the two bytes of `é` are
each meaningless alone.

Bytes are still available where bytes are meant — `std.bytes` hands
back a `byte[]` — but that is a different question from what a string
is made of.

### A string of one character

What Python does.  Nothing new to implement, and every string
operation works on the element.

Against it: an element of a string is then a container of itself,
which is a circularity a reader has to unlearn, and it makes the type
say nothing.  A function taking one character and a function taking a
string have the same signature, so neither says what it wants.

### A distinct type holding a Unicode scalar value — chosen

`char`, holding UCS-4: any code point, one value per character
whatever its encoding costs.  Rust's `char` is this, and Go's `rune`
is the same idea attached to `int32`.

## A Character Is Not a Number

Go makes `rune` an alias for `int32`, so `c + 1` compiles and produces
something that is a character only if you are lucky.  Making the type
distinct is what stops that: a number becomes a character where the
program says `.chr()`, and a character says its number where the
program says `.ord()`.  Nothing converts implicitly in either
direction.

That is also why `.chr()` is on the integer types and `.ord()` is on
`char` — the conversion is written at the value that has it, and reads
in the direction it goes.

## What Is Not a Code Point

Three things a number can be that a character cannot:

- **Negative.**  Characters are numbered from zero.
- **Past 0x10FFFF.**  That is the last code point; UCS-4 has room for
  more, and Unicode does not.
- **A surrogate**, 0xD800…0xDFFF.  These encode half of a character in
  UTF-16 and are not characters themselves.  Excluding them is what
  keeps every `char` encodable as UTF-8, which the language requires of
  its strings.

The last of these is the one worth stating, since a language that
allowed it would have `char` values its own strings could not hold.

## Reporting a Negative Constant Early

`.chr()` on a negative number is an error whenever it runs, but where
the number is written down, running is not needed to know:

```
(⁻1).chr()

error: chr: -1 is not a code point; a character is numbered from 0
```

This is the same rule the language already applies to an integer
literal its type cannot hold — the mistake is in the text, so it is
reported at the definition, in a function nobody calls as much as in
one that runs.  The check reads through the `⁻` the way the evaluator
does, since a negation written against a literal is part of it.

## Displayed and Written

Two different jobs, and the type does them differently:

- `std.print("{}", c)` **writes** the character, as printing a string
  writes its text.
- The prompt **displays** it as `'a'`, quoted the way a character is
  written rather than the way a string of one would be, so a value read
  back says which it is.

## Status

Implemented: the type, `foreach` over a string, `.ord()`, `.chr()` on
every integer type, the three refusals, the definition-time check for a
written negative, comparison by code point, and formatting.

Not implemented:

- **A character literal.**  There is no way to write `'a'` in source; a
  program says `97u32.chr()` or compares against a character taken from
  a string.  This is the obvious next thing and needs a decision about
  quoting, since `"` is the string's and the apostrophe appears in
  prose.
- **Characters and strings together**: no `⧺` between them, no way to
  build a string from characters, no indexing a string by position.
- **Character classification** — whether a character is a digit, a
  letter, upper or lower case — which is a Unicode-table question
  rather than a language one.
