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

### Asking `⍳` — `(v ⍳ x) ≠ ∅`

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

## One Thing at a Time

The left operand is a single value and the answer is a single `bool`.

APL's rule is the other one: there the answer takes the shape of the
left operand, so an array on the left asks the question of each of its
elements at once and gets one answer for each.  That was implemented
first and then taken out.  Two reasons:

**An operator that answers a bool is worth more than one that answers
either.**  `∊` is a predicate, and a predicate that sometimes hands
back an array is one a condition cannot be given without checking
first.  Asking the question of every element of an array is a fold or a
map over the question, not the question.

**It made a run of characters mean something.**  If an array on the
left asks its elements one at a time, a string on the left is the same
shape of question — and then `"ell" ∊ "hello"` has to mean *something*.
Either it is a substring test, which is not membership at all, or it is
the characters of `"ell"` asked one at a time, which is a different
answer to the same source.  Neither is worth having: a string holds
characters, so a run of them is not one of the things it holds.

Whether a run is in a string is a real question and it already has an
answer — `⍳` says where a run starts, so `(s ⍳ "ell") ≠ ∅` asks it.
The refusal names that:

```
"ell" ∊ "hello"

error: ∊: a string holds characters, and a run of them is not one of
them; ⍳ says where a run starts
```

A string on the left *is* a single value where the container holds
strings, since there it is one of the things the container holds:
`"two" ∊ words` on a `str[]`.  What decides is the container, not the
operand.

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
that, an element is compared by going through `=`, which is where the
unit rules already live.

This was stricter than `⍳`, which answered `∅` when asked for
something of an unrelated type because that is what `=` answers.  The
two ask the same question of their operands, so `⍳` was tightened to
match and both now go through one check.  What settled which way to
close the gap: `=` is asked about two values a program has in hand,
where a search is asked about a value and a *container*, whose type
says what could ever match before anything is compared.

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

## A Bug It Turned Up

Writing the refusal for a run of characters meant writing what to do
instead, and `(s ⍳ "ell") ≠ ∅` did not work: comparing a *found*
position with `∅` was a type error, while comparing an absent one was
fine.  A position carries a unit, and the operator dispatch unwrapped
the optional to find the unit before anything had asked whether there
was a value at all.

Whether there is one is now settled first for `=` and `≠`.  The
`⍳` tests had only ever compared absent positions against `∅`, which is
the case that worked; the ones that compare a found position are there
now.

## Status

Implemented: on vectors, on slices of them, on matrices to any depth,
and on strings, for a single value on the left; answering one `bool`;
settled at compile time where both operands are.
