# Choosing a Value

## The Question

The language could branch and could not choose.  Every `if` was a
statement, so picking between two values meant a mutable name and two
assignments to it:

```
let n : mut i64 = 0
if x > 0:
    n ← x
else:
    n ← ⁻x
```

Three statements, and a `mut` on something that never changes after the
first thing written to it — which is exactly what `mut` is supposed to
warn a reader about.  The language has a warning for a `mut` that is
never modified; this shape produces the opposite, a `mut` that is
modified once and means nothing by it.

## The Spelling

Python's: `a if c else b`.  It was asked for, and the alternatives are
worth recording anyway.

| | | |
|-|-|-|
| C, C++ | `c ? a : b` | two glyphs spent, and `?` is already the optional suffix |
| Haskell, ML | `if c then a else b` | would want a `then` keyword the language does not have |
| Rust | `if c { a } else { b }` | a different and larger answer — see below |
| **Python** | **`a if c else b`** | **chosen** |

The complaint against Python's order is that it reads out of sequence:
the value comes before the question it answers.  The complaint is fair
and is outweighed here by two things.  It costs no new token — `if` and
`else` are already keywords, and no glyph is spent, which matters in a
language that is spending its glyphs deliberately.  And the value is
usually the thing the reader is after; the condition is the caveat.

**Rust's answer is the more general one** and was seriously considered:
make every block an expression, and the conditional disappears as a
separate feature because `if c { a } else { b }` already is one.  It was
not taken because it is a much larger change than choosing between two
values — it decides what *every* `if`, `match` and block in the language
evaluates to — and it deserves to be decided on its own.  Nothing here
forecloses it: Python has both, and `a if c else b` remains the short
way to write the common case.

## Only the Branch Taken Is Read

This is not an optimisation, it is the feature.  It is what lets a
conditional stand in front of the thing it guards against:

```
0 if n >= #v else v[n]
```

Written the other way — evaluating both and choosing after — that line
would fail on exactly the input it exists to handle.

## The Hazard Worth Writing Down

The precedence levels call `_skip_nl()` at the top of their loops
looking for an operator, and **do not put the newline back** when they
do not find one.  So an expression that ends a line leaves the parser
sitting on the next line's first token.

That is harmless while nothing after an expression cares — the block
loop skips newlines itself — and it stops being harmless the moment an
expression may be followed by `if`:

```
    foo()
    if bar:          // would be read as `foo() if bar else …`
```

Two ways out.  Make every level restore the position it skipped from,
which is the tidier fix and touches every precedence level in the
parser for the sake of one feature.  Or ask, where the `if` is found,
whether a newline was crossed to reach it — which is one line and reads
as what it means:

> An `if` goes on with the expression only where the token in front of
> it is not a line break.

That is what is implemented.  A following `if` statement always has a
newline in front of it; a same-line `if` never does.  And inside
`( … )` the lexer emits no newlines at all, which is what lets a
conditional be written across lines there without any further rule.

## `else` Is Required

An `if` statement may have no `else`, because a statement that does
nothing is a thing.  An expression that produced no value would not be,
so the second value is not optional, and the refusal says so rather
than reporting a syntax error at whatever followed.

## The Two Sides Say One Type

A conditional is one value, so its two sides have to say one type
between them, and a pair that cannot be the same value is refused at
the definition.

The hard part was not the comparison but knowing when *not* to make it.
Three kinds of pair look like a disagreement and are not:

- **A number with no width stated.**  `1 if c else 2.5` is an int and a
  float on the page and one `f64` in a binding that asks for one, since
  an unwidthed literal settles on what it is asked for.
- **An absent value.**  `7 if c else ∅` is not a disagreement between
  `i64` and nothing; it is an `i64?`, which is the type that holds
  both.
- **Two types a sum type joins.**  `type Width = i32 | i64` says those
  two belong together — that is the whole of what a sum type is for —
  so `a if c else b` over them is one `Width`.

The last one is the interesting case, because the check cannot see the
type the value is going *to*.  What it can see is every sum type the
program declared, and asking whether any of them holds both is exactly
the question: the two are one value only if something said so.  Without
such a declaration the same line is refused, which is the honest
answer rather than a guess in either direction.

The consequence is worth stating plainly: **declaring a sum type
elsewhere makes a conditional legal here.**  That reads as action at a
distance, and it is — but the alternative is refusing a program that is
right, or accepting every pair and checking nothing.

## What It Reads, and What It Leaves Alone

Only what the program writes down: a literal, a name's declaration, a
struct field, a comparison.  Both sides have to say what they are for
the pair to be judged at all, so anything reached through a call, a
subscript or arithmetic leaves the conditional alone.

Arithmetic is the deliberate omission.  `a + b` where both are stated
widths raises width unification, which is a question worth answering
properly and separately rather than half-answering here to catch one
more case.

## Status

Implemented: the expression in every position a value is wanted;
right-grouping chains; the condition read for truth as an `if`
statement reads its own; `else` required; a conditional built from
constants counted as a constant, so `@typeof` and the other
compile-time forms answer for one; and the two sides refused at the
definition where they cannot be one value.
