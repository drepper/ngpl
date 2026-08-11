# A Number Outside the Range Its Type Can Hold

## The Question

Integer overflow was reported from the beginning: a result the type
cannot hold is a mistake, not a number to adjust.  Floating point had
no such rule, and it turned out to have three separate holes:

```
let d := 3e400f64          // inf
let c : f32 = 3e40         // "float too large to pack with f format"
3e300f64 × 3e300f64        // inf
1e-300f64 × 1e-300f64      // 0.0
```

An infinity and a zero are numbers a program goes on computing with as
readily as any other, so each of these hands back an answer that is not
the one the source asks for.  The question is where to draw the line —
a float format has somewhere to put such a value, which is exactly what
makes the silence possible.

There was a fourth hole with the same shape on the integer side: a
literal whose type could not hold it was reported only when the code
holding it ran.

## The Rule

**A value that would stop being the number it is, is refused.**

Overflow makes it an infinity and underflow makes it a zero.  Both are
reported, wherever the value is written down and wherever an operation
produces one.

What follows from that rule rather than being decided separately:

- **Rounding is not overflow.**  A value the format rounds to something
  it can hold is held; `3.4028235e38` is an `f32`.
- **A subnormal is not underflow.**  It is a number the format holds,
  with fewer significant bits than a normal value but not with none.
  Only reaching zero loses the value entirely.
- **A zero from `+` or `-` is exact.**  It says the two operands were
  equal, so those operators are asked about overflow only.  Underflow
  is asked about for `×`, `÷`, and `↑`.
- **A zero operand gives an exact zero.**  `0.0 × 5.0` is the answer,
  not a loss.

## Considered

### Report only at literals

The smallest change, and where the report is most obviously right: the
mistake is in the text. Rejected as incomplete — `3e300f64 × 3e300f64`
is the same defect one step later, and a program that has multiplied
two numbers and been handed an infinity is no better off for the
literals having been checked.

### Report at literals, and let arithmetic answer with an infinity

What the specification said before this work, and the reason given for
`⊞` being integers-only: a float "answers overflow with an infinity and
has no such edge".  The position is defensible — IEEE 754 defines the
result, and a program may mean to compute with infinities.

Rejected because it is not the position the language takes about
integers, and the reason for that position does not change with the
type.  The rationale for `⊞` had to be rewritten: saturating is
integers-only now because a float already *has* an answer for a result
that will not fit, and holding it at the largest value the format
happens to have would be a rounding decision rather than a bound the
program stated.

### Report everywhere — chosen

Literals, values being given to a type, and results of operations.

## Where It Is Checked

The literal check has to be in the lexer, because that is the last
place the value still exists: `float("3e400")` is `inf` and
`float("1e-400")` is `0.0`, and by the time the parser sees the token
the number that was written is gone.  This is also why the underflow
check reads the literal's *digits* — the parsed value cannot tell
`1e-400` from `0.0`, but an exponent cannot make a nonzero number zero,
so the significand says which was written.

Everything else is checked where the value meets the type: a binding,
an argument, a struct field, an array element, a return.  That last one
was doing nothing at all for floats — a function declared `→ f32` handed
back whatever width its body had — and had to be made to coerce as the
integer branch beside it already did.

The integer literal check moved from the evaluator to the definition,
so a literal in a function nobody calls is checked with the rest.

## `⁻` Against a Literal

Making the integer check happen at the definition exposed something the
runtime check had been hiding: `⁻128i8` was refused, because `128i8`
had to be an `i8` on the way to being negated.  The lowest value of
every signed type was unwritable — the problem C works around in its
library, where `INT8_MIN` is spelled `(-127-1)`.

A `⁻` written directly against a literal is now part of the literal, in
the static check and in the evaluator alike.  *Directly* against it:
in `⁻2↑2` the `↑` takes the `2` first, so the `⁻` applies to the power.
The rule needs no list of which operators bind tighter, because by the
time the evaluator sees the negation it can tell whether its operand is
a literal or an expression.

## What This Costs

An infinity and a NaN are now unreachable in the bootstrap: a literal
cannot name one, arithmetic reports rather than producing one, and
division by zero answers with an error value.

That is what makes the checks cheap — nothing has to tell an infinity
that was meant from one that was an accident — and it is also a debt.
The full language wants both, and the design notes already call for
faulting on Inf and NaN in a deferred way, which needs them to exist
first.  The specification says so where it states the rule, rather than
leaving a reader to notice the absence.

## Status

Implemented for `f16`, `bfloat16`, `f32`, `f64`, and the untyped float:

- a literal that overflows or reaches zero, in decimal and in hex;
- a value being given to a type that cannot hold it, at every site
  where a width is settled;
- an operation whose result leaves the range, for `+ - × ÷ ↑`.

An untyped float literal is diagnosed against `f64` and says why: the
bootstrap holds one in an `f64` until the arbitrary-precision float
arrives, and nothing in the source said `f64`.

Not implemented: rounding modes, and any way to ask for an infinity on
purpose.
