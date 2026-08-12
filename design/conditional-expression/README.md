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

## What Is Not Checked

That the two branches agree in type.  They need not, and the value is
whichever branch ran:

```
@typeof(1i64 if true else "x")      // i64
@typeof(1i64 if false else "x")     // str
```

For a language that means to catch what it can before anything runs,
this is a gap rather than a decision.  Closing it needs a pass that
knows what type an arbitrary expression has, which does not exist yet
and is worth having for more than this.

## Status

Implemented: the expression in every position a value is wanted;
right-grouping chains; the condition read for truth as an `if`
statement reads its own; `else` required; a conditional built from
constants counted as a constant, so `@typeof` and the other
compile-time forms answer for one.
