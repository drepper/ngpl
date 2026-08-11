# An Operator Where a Function Goes

## The Question

A fold takes a function:

```
(λa : i64, b : i64 → i64: a + b) ⌿ nums
```

The lambda says `+` three times over — once in the body and twice more
in the types it has to state to be written at all.  What the fold wants
is the operator, and the operator was not something that could be
written on its own.

## What Was Chosen

An operator may stand where the fold's function goes:

```
+⌿ nums                 // the sum
×⌿ nums                 // the product
⌈⌿ nums                 // the largest
⧺⌿ chars                // the string those characters spell
```

This is APL's `+/`, which is where the glyphs come from, and it is the
form that makes a fold worth having: `+⌿` is a word, and the lambda
version is a sentence.

## The Rule That Keeps It Unambiguous

An operator is a value **only** directly before a fold glyph.  The
parser reads one when the token is a binary operator and the next token
is `⌿` or `⍀`; anywhere else an operator means what it always meant and
needs its operands.

That position is exactly where an operator could not otherwise appear,
so nothing that parsed before parses differently now.  It is a narrow
rule rather than a general one, and the narrowness is the point:
making operators first-class values everywhere would raise questions
this does not — what `+` alone means as an argument, whether it can be
bound to a name, what its type is — and none of those need answering to
write `+⌿ v`.

## One Implementation, Two Spellings

`a + b` and `+⌿ v` reach the same code.  Applying a binary operator to
two values it has already been given was inline in the expression
evaluator; it is a method now, called from the operator-between-operands
path and from the operator-as-value path.  So the two spellings agree by
construction rather than by two implementations happening to match —
including the parts easy to forget, like a unit travelling through the
operation and an operand that is an array being handled element-wise.

## Status

Implemented for the binary operators: `+ - × ÷ % ⊞ ⊟ ⊠ ⌈ ⌊ ⧺ ↑ & | ^
« » ↺ ↻ ∧ ∨ ⊕ ⊼ ⊽`, in both fold directions and with or without an
initial value.

Not implemented:

- **`??`**, which chooses whether to evaluate its right operand and so
  is not a function of two values.
- **Operators as values anywhere else** — as an argument, bound to a
  name, or composed.  That is the general question this deliberately
  did not answer.
- **A unary operator as a value**, which would need a way to say which
  arity is meant.
