# Asking Something of Each

## The Question

The language could fold a container and could not map one.

`f ⌿ v` reduces, `⍴` reshapes, `⧺` joins — and the most ordinary thing
anybody does to an array, apply a function to each of its elements, had
no spelling at all.  What existed instead was `generate(f, 1…5)`, which
makes a container from a range, and `@listable`, which is a promise the
*function* makes.

## Why `@listable` Was Not Enough

Every operator in the language threads over what it is handed, and a
function marked `@listable` does too.  So a reader might reasonably ask
what a map operator is for:

```
⁻v                              // already each of them
v × 2                           // already each of them
tripled(v)                      // already each of them, if tripled is @listable
```

The answer is that `@listable` is a property of the **definition**.  It
says *every* call threads, which is a promise about every use of the
function, and it is refused where the function takes a parameter by
reference or has no fixed positions.  Most functions are not listable
and should not be: threading is a thing a particular *call* wants, not
usually a thing the function is.

`¨` says it at the call.  That is the whole of the difference, and it is
why both exist: `f(v)` where `f` is listable and `f¨v` where it is not
say the same thing in the two places the choice can be made.

## The Spelling

APL's, unchanged: `f¨v`, and APL calls it *each*.  The glyph was free —
`¨` is U+00A8 and the lexer read it as part of an identifier, which no
program was doing on purpose.

The position follows the fold: function on the left, data on the right.
That was already the language's shape for `⌿` and `⍀`, and the argument
made for it there — the operation is what you are reading, the container
is what it is reading — applies unchanged.

**One departure from APL.**  There `¨` is an *operator modifier*: it
takes a function and makes a new one, which is then applied.  Here it is
a binary operator that answers the array directly.  The fold made the
same simplification, and for the same reason: a modifier would need the
language to have derived functions as values, which it does not.  Where
that arrives, `¨` can become one without changing what any existing
program means.

## What It Takes and What It Answers

Arrays and ranges, which is what the fold takes.  A matrix holds rows,
so each of them is a row — the same reading `#` gives when it answers
the outer dimension.

An empty container answers an empty array.  There is nothing to ask
about, and that is an answer rather than a failure — unlike a fold with
no initial value, which has nothing to *start* from and says so.

The answers need not be of the element's type.  `describe¨v` on numbers
answers strings, and that is the point of mapping rather than threading
an operator, which can only ever answer what the operator answers.

## How Far Right It Reaches

`¨` takes everything to its right as the container, which is what the
fold does.  So `f¨a ⧺ b` maps over the join rather than joining the map
to `b`.

This is worth flagging because it is the one thing a reader coming from
Haskell or Rust will get wrong: `map f xs ++ ys` there parses the other
way.  The consistency argument won — a language whose combinators do not
agree with each other about where their operand ends is worse than one
that is uniformly greedy — and brackets say the other thing.

## Status

Implemented: `f ¨ v` over an array or a range, with a named function, a
lambda, or a name that holds one on the left; a matrix mapped by rows;
an empty container answering an empty array; and a refusal naming what
was handed over where it holds nothing to ask about.

Left for later: `¨` over a hash or a set, which raises the question of
what a map of a hash *is* — its values, or its pairs — and deserves to
be answered with the rest of what those containers do.
