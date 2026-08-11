# The Larger and the Smaller: `⌈` and `⌊`

## The Question

Taking the larger or the smaller of two numbers is arithmetic, and the
language had no way to write it.  A program had to write the
comparison out, or reach for a function that did not exist.

What had to be decided was not whether to have it but what shape it
takes: a function or an operator, how tightly it binds, what it does
about types and units, and whether the glyphs keep the second meaning
APL gives them.

## Considered

### A function — `max(a, b)`

What C, Python, and Rust do, in their various spellings.  Nothing
against it except what it costs at the point of use: an expression
that was arithmetic stops reading as arithmetic.

Clamping is the case that decides it, being what these are mostly for:

```
(n ⌈ 0) ⌊ 100
min(max(n, 0), 100)
```

The first says the same thing in the order it happens.

### An operator — chosen

`⌈` (U+2308 LEFT CEILING) for the larger and `⌊` (U+230A LEFT FLOOR)
for the smaller, which is what APL, BQN, and their descendants use.
The glyphs are already read this way by everyone who has met an array
language, and they are not spellings of anything else here.

## Grouping

A new level between the comparisons and the shifts: looser than every
arithmetic and bitwise operator, tighter than the comparisons and `…`.

The operands are usually computed and the answer is usually compared,
so this is the grouping that needs no parentheses in either direction:

```
2 + 3 ⌈ 10 - 4      // the larger of the two sums
3 ⌈ 5 == 5          // compares the answer
1…(2 ⌈ 3)           // a range bound
```

Left-associative, which changes nothing: both operators are
associative, so `a ⌈ b ⌈ c` is the same value read either way.

## What the Answer Is

The result is *one of the operands* rather than something computed from
both.  That settles several questions at once:

- **No range of its own.**  Whatever width the two settle on holds a
  value that already fitted in one of them, so neither operator can
  overflow and `@wrap` has nothing to do there.
- **Same kind of number, as for addition.**  `1 ⌈ 2.5` is refused
  rather than compared exactly; comparing an integer with a float
  exactly is rarely the question a program means to ask, and the
  language already says so at `+`.
- **Units travel as through `+` and `-`.**  The operands must measure
  the same thing, the answer carries the unit, and operands written in
  different scales of it are compared by what they measure:
  `5¤meter ⌊ 300¤centimeter` is `3 m`.  The larger of a length and a
  duration is not a question with an answer.
- **Element-wise on arrays**, like the arithmetic operators, between
  two arrays or an array and a scalar.

## Only the Dyadic Meaning

APL gives each glyph a monadic meaning too: `⌈x` is the ceiling of `x`
and `⌊x` its floor.  Not provided here.

A glyph whose meaning depends on how many operands it was given has to
be read twice — once to count, once to understand — and the language
has taken fixed arity elsewhere for the same reason.  Rounding a float
will get a name of its own when it arrives.

## A Collision Worth Knowing About

`@max(T)` and `@min(T)` already exist and mean the extreme values a
*type* can hold.  Zig has the mirror image of this: there `@max(a, b)`
takes two values.  The specification cross-links the two in both
directions, since a reader who meets one will wonder about the other.

## Status

Implemented: both operators, at the precedence above, on integers and
floats, with units, element-wise on arrays, and settled at compile time
where both operands are.

The extreme of a whole vector is the fold of the operator over it,
written with a lambda:

```
(λa : i64, b : i64 → i64: a ⌈ b) ⌿ [3, 1, 4, 1, 5]
```

An operator is not a value yet, so `⌈ ⌿ v` does not parse.  When
operators become first-class that is what this should look like.
