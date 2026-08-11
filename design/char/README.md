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

## Writing One Down

`'a'`, between apostrophes, with the string keeping its double quotes.
Both are what C, C++, Rust, and Java use, and the pairing is what makes
`'a'` and `"a"` say which they are before they are read — which matters
here more than in those languages, since the two are different types
rather than a character and an array of one.

The apostrophe was the question, because the language already uses one:
a generic type name ends in a prime, `T'`.  There is no conflict in
practice, and the reason is worth writing down.  An apostrophe that
*continues* an identifier is taken by the identifier scanner, so one
that reaches the literal scanner is at the start of a token, which is
where a literal may begin and a type name may not.  `f(args… : T')` and
`f('a', 'b')` both read, and so does the first followed by the second.

A literal holds exactly one character.  `''` and `'ab'` are refused
rather than being an empty character and a string, and each says what
to write instead, since the mistake is nearly always a string written
with the wrong quotes.

The escapes are the string's, with `\'` in place of `\"` — and `\u{…}`,
which is the same conversion `.chr()` performs and refuses the same
three numbers.  A literal written that way is checked as it is read,
so `'\u{D800}'` is a lexical error rather than a value.

### A member call on a literal

`'a'.ord()` had to work, which meant letting a postfix chain follow a
literal.  It follows a string literal now too, so `"abc".sizeof`
reads.  Numbers are still excluded, for a lexical reason rather than a
principled one: `65.chr()` cannot be scanned, since `65.` begins a
float.  `(65).chr()` is how a number literal says it.

## Building One Back Up

Taking a string apart wants a way to put one together, and the language
had two candidates for it.

`+` concatenates strings today.  It is not the one to extend: the
specification's own reason for having `⧺` is that `+` should not be
overloaded, since on arrays it is element-wise addition.  Joining a
character with `+` would also read as arithmetic on a character, which
is the thing the type exists to prevent.

`⧺` is the one.  It joins two sequences, and a string and a character
are both text, so joining either with either gives a string:

```
'a' ⧺ 'b'           // "ab"
"ab" ⧺ 'c'          // "abc"
out ← c ⧺ out       // reversing a string, one character at a time
```

This also gives `str ⧺ str`, which had been missing — `⧺` took arrays
only, so the operator the specification called *the* concatenation
could not concatenate the language's own text.

For the bulk case, `.str()` on a character and on an array of them.
The conversion is written at the value that has it, which is where
`.ord()` and `.chr()` already are.

`.str()` asks for characters and not bytes.  A `byte[]` is an
*encoding* of characters, and turning one back into text is decoding —
a fallible operation with a different signature, which the language
does not yet have.

### A number does not join text

Considered and rejected: letting `⧺` take an integer as the character
it numbers, so that a vector of code points could be folded straight
into a string with `⧺⌿ codes`.

It is tempting because an operand of `⧺` is being written into a
string, and a number written into a string one character at a time can
only mean the character it numbers.  It was tried, and the reason it
came out again is what it does to the other reading:
`"total: " ⧺ 5` becomes `"total: \u{5}"` — a control character in the
output — where a reader expects `"total: 5"` or an error.

A number is not text, and which of the two it was meant as is not
something the operator can decide.  So it is refused, and the message
names both ways across:

```
"n=" ⧺ 65

error: ⧺: the right operand is int, which does not go together with
text; a number becomes the character it numbers with .chr(), and its
digits with std.format
```

A vector of code points is folded into a string by saying the
conversion where it happens:

```
(λa : str, b : u32 → str: a ⧺ b.chr()) ⌿ (codes, "")
```

which is longer than `⧺⌿ codes` and says a thing that is true.

## Status

Implemented: the type, `foreach` over a string, `.ord()`, `.chr()` on
every integer type, the three refusals, the definition-time check for a
written negative, comparison by code point, formatting, literals,
`⧺` between text, and `.str()`.

Not implemented:

- **Taking a string apart other than by iterating it**: no indexing by
  position, no `.chars()` handing back an array, no slicing.
- **Decoding a `byte[]`**, which is where UTF-8 stops being an
  implementation detail and becomes an operation that can fail.
- **Character classification** — whether a character is a digit, a
  letter, upper or lower case — which is a Unicode-table question
  rather than a language one.
- **`.ord()` at compile time.**  `static_assert('a' < 'b')` holds,
  since both sides are literals, but `static_assert('a'.ord() == 97)`
  does not: a member call is not a constant expression, and deciding
  which ones could be is a question about purity rather than about
  characters.
