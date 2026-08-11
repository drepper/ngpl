# Equality Is `=`, Inequality `≠`

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

## Inequality Followed

`!=` became `≠` (U+2260 NOT EQUAL TO) straight afterwards, as a
separate change because it is a separable one.

The argument is thinner than the one for `=`, since `!=` was not
*wrong* — nothing else wanted the spelling.  What decided it is that
`=` and `!=` do not read as a pair.  They ask one question and its
negation, and the glyphs should show that as `⌈` and `⌊` do; `≠` is `=`
with a stroke through it, which is exactly the relation.  Leaving the
mixture would have meant one operator spelled the way mathematics
spells it and its own negation spelled the way C spells it.

One wrinkle is worth recording.  `!` is a type suffix — `i64!` is the
expected type — so `!=` can arise from a type written hard against a
definition's `=`.  `let x : i64!= 10` is refused, and it was refused
before this change too, since `!=` was a single token then as well.
Keeping `!=` lexed as one token for the sake of the migration
diagnostic leaves that exactly as it was rather than making it worse,
and a space is all it ever needed.

## The Old Spellings

Both are refused by name rather than falling out as a parse error:

```
x == 5

error: '==' is not an operator; equality is written '='

x != 5

error: '!=' is not an operator; inequality is written '≠'
```

Every program written before this change uses them, so the diagnostics
are worth more than the tokens are.  They can go once nothing reaches
for them.

## Comparison with Other Languages

| Language | Equality | Inequality | Assignment |
|----------|----------|------------|------------|
| C, C++, Java, Python, Rust, Go | `==` | `!=` | `=` |
| Pascal, Ada | `=` | `<>` / `/=` | `:=` |
| ML, Haskell | `=` / `==` | `<>` / `/=` | — |
| APL, BQN | `=` | `≠` | `←` |
| Julia | `==` | `!=`, `≠` | `=` |
| NGPL | `=` | `≠` | `←` |

C and its descendants spell equality `==` for one reason: `=` was
assignment first.  Pascal gave assignment `:=` and got `=` back.  APL
gave it `←` and got both glyphs back, which is the route taken here.
Julia accepts `≠` as a synonym for `!=` but keeps `==`, since its `=`
is assignment.

## Status

Implemented.  `=` is equality and `≠` inequality, at the comparison
level; `←` is the only assignment; `==` and `!=` report the new
spellings.
