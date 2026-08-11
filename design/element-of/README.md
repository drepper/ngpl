# Whether Something Is There: `∊`

## The Question

[`⍳`](../index-of/README.md) answers where something is, and a program
that only wants to know *whether* has to write the position it does not
want and then ask whether there was one.  The question is common enough
to have its own operator in every language that has thought about it.

What had to be decided: whether it is a second reading of `⍳` or an
operator of its own, what it may be asked about, what shape the answer
takes, and how much it insists on before it answers.

## Considered

### Asking `⍳` — `(v ⍳ x) != ∅`

Already possible, and it says the wrong thing at the point of use: the
position appears in the source so that it can be thrown away, and a
reader has to work back from it to the question.  It also cannot be
asked of a matrix at all, for the reason in the next section.

### A method — `v.contains(x)`

What C++, Rust, and most of the rest do.  The objection is the one
`⍳` met: text and arrays end up with separate spellings, and the
question reads as something done *to* the container rather than as a
question about the two operands together.

### An operator — chosen

`∊` (U+220A SMALL ELEMENT OF), which is APL's, and which is the
mathematical notation for exactly this.  Python and Julia read the same
way with `in` and `∈`.

The left operand is what is looked for and the right is what is looked
through, which is the order the mathematics has and the reverse of
`⍳`'s.  That is worth stating plainly because the two operators sit
next to each other:

```
v ⍳ 20      // where in v is 20
20 ∊ v      // is 20 in v
```

Each reads as its own sentence in its own order — *where in v is 20*
and *20 is in v* — which is why neither was turned round to match the
other.

## Whether Answers Where Where Cannot

`⍳` refuses a matrix: a position in one is not one number, and there is
nothing honest to answer.  `∊` has no such trouble.  Whether something
is in a matrix is a question with a yes or a no, so the right operand
is looked through whole, to the numbers in it, however many dimensions
it has.

This is the one place the two operators deliberately differ in what
they accept, and the reason is worth keeping in view: a position has to
say *where*, and this says only *whether*.

## The Shape of the Answer

The answer takes the shape of the *left* operand, which is APL's rule:

- a scalar asks one question and gets one answer;
- an array asks the question of each of its elements and gets one
  answer for each, in the shape it was asked.

So the two operands are read differently — the left one element by
element, the right one as a whole — which is what makes `[10, 99] ∊ v`
two questions and `20 ∊ m` one.

A string is text rather than an array of characters, so `"ell" ∊
"hello"` is one question about a run of characters, matching what `⍳`
does with the same operands.  Asking of each character on its own is
asking of an array, which is what `.chars()` gives.  Without that rule
the same two operands would mean one thing under `⍳` and another under
`∊`.

Unlike APL the answer is a `bool` rather than a `0` or a `1`.  The
language has the type, and a condition asks for it.

## What It Insists On

What is looked for has to be the kind of thing the container holds.  A
program that asks whether a string is among some numbers has made a
mistake about one of the two, and answering `false` would let it carry
on believing both.

The check is the language's existing one for whether two scalars are
the same kind of thing — the rule that lets a width meet another width
and a number meet a float, and stops a string meeting either.  Past
that, an element is compared by going through `==`, which is where the
unit rules already live.

This is stricter than `⍳`, which answers `∅` when asked for something
of an unrelated type because that is what `==` answers.  The two should
probably agree; that `⍳` is the one to tighten is a decision for
whoever gets there next.

## Grouping

The same level as `⍳`, `⌈`, and `⌊`: looser than the arithmetic
operators, tighter than the comparisons, `…`, and the logic operators.

What is looked for is often computed and the answer is usually fed to a
condition or combined with another, so nothing in either direction
needs parentheses:

```
n + 10 ∊ v
20 ∊ v ∧ 30 ∊ v
```

## Left for Later

**A range.**  `3 ∊ (1…5)` is refused, since a range is a pair of ends
rather than something to look through.  Python and Julia both answer it,
and a range is ordered, so the question could be settled by two
comparisons rather than by looking at anything.  It was left out
because the right operand was specified as a container; it is a small
and self-contained addition when it is wanted.

**A set.**  The language has no set type yet.  When it arrives, this is
the operator it should answer to, and the mathematical reading of the
glyph will be exactly what it means.

## Status

Implemented: on vectors, on slices of them, on matrices to any depth,
and on strings, for a scalar or an array on the left; answering a
`bool` or an array of them in the shape of the left operand; settled at
compile time where both operands are.
