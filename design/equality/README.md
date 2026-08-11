# Equality Is `=`

## The Question

Equality was `==`, which every C-descended language spells that way for
one reason: `=` was taken by assignment before equality needed a glyph.
This language does not assign with `=` — it assigns with `←` — so the
inherited spelling was paying a cost for a conflict it does not have.

What had to be decided was whether the conflict is really absent, since
`=` appears in a definition too.

## The Conflict That Did Exist

The parser accepted `x = 5` as an assignment, alongside `x ← 5`.  It
scanned a statement for a bare `=` at bracket depth zero, skipping
`==`, and took what it found as a store.

That is what made the rename impossible: with `=` meaning equality,
`x = 5` would have gone from storing 5 to comparing and discarding the
answer.  Nothing in the language's own documents asked for that
spelling — the reference manual's assignment table lists only `←`, and
the design brief says assignment uses `←` — so it was a second way to
write something that already had one, and it went.

Removing it also removed a wart it had caused.  `while e: x = 5` was
rejected, because an inline body that happened to be an assignment had
the same shape as a typed binding `while e : T = expr`.  The
restriction stays — an inline body that is a *comparison* has the same
shape — but assignment is no longer one of the things that can be
confused with a binding.

## The Conflict That Did Not

`=` also separates a definition from its value: in `let`, in an `enum`
member, in a `type` or `unit` definition, and in the binding forms of
`while` and `foreach`.

This is not an ambiguity, because each of those consumes its `=` at a
fixed point, before any expression begins.  An `=` reached while an
expression is being read is therefore the operator, and the two meet
without interfering:

```
let b : bool = x = 5
```

The parser has to do nothing clever to tell them apart — the first `=`
is eaten by the definition's own grammar, the second by the comparison
level of the expression grammar.  This is the same way a minus sign
tells its two readings apart, by where it is written.

## What Is Bought

**The glyph mathematics uses for equality means equality.**  `x = 5`
reads as it is read aloud.

**The C bug cannot be written.**  `if (x = 5)` where `==` was meant is
the classic mistake, and languages have gone to some trouble to catch
it — warnings, requiring extra parentheses, forbidding assignment in a
condition.  Here the mistake has nothing to land on: `=` compares, `←`
stores, and a comparison in statement position is caught by the
unused-value rule:

```
x = 5

error: the value of this statement is not used; it computes something
and nothing reads it
```

## What Was Left Alone

`!=` keeps its spelling.  `≠` is the glyph that would match `=` the way
`⌈` matches `⌊`, and taking it would be a second, separable change; the
pairing `=` / `!=` is at least no worse than the `==` / `!=` it
replaces.

## The Old Spelling

`==` is refused by name rather than falling out as a parse error:

```
x == 5

error: '==' is not an operator; equality is written '='
```

Every program written before this change uses `==`, so the diagnostic
is worth more than the token is.  It can go once nothing reaches for it.

## Comparison with Other Languages

| Language | Equality | Assignment | Why |
|----------|----------|------------|-----|
| C, C++, Java, Python, Rust, Go | `==` | `=` | `=` was assignment first |
| Fortran (early), COBOL | `.EQ.`, `=` | `=` | context tells them apart |
| Pascal, Ada | `=` | `:=` | assignment took the second glyph |
| ML, Haskell | `==` (or `=`) | — | `=` binds a definition |
| APL, BQN | `=` | `←` | the same split as here |
| NGPL | `=` | `←` | |

Pascal and APL both reach this by the same route: give assignment its
own spelling and equality is free.  APL's is `←`, which is the one
already in use here.

## Status

Implemented.  `=` is equality at the comparison level, `←` is the only
assignment, and `==` reports the new spelling.
