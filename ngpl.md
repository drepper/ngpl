# NGPL

Design notes for the language.  The reference manual is
[spec/spec.md](spec/spec.md); the documents below record the questions
each feature had to answer, what was considered, and why the answer is
what it is.

## Design Documents

- [Sum Types](design/sum-types/README.md) — how a program says a value
  is one of several alternatives
- [Static Analysis: Effects and Unused Values](design/static-analysis/README.md)
  — what a program has to say about its side effects, and what happens
  to a value nothing reads
- [The Larger and the Smaller: `⌈` and `⌊`](design/minmax/README.md) —
  taking one of two numbers, as an operator rather than a function
- [A Number Outside the Range Its Type Can Hold](design/number-range/README.md)
  — why a float that overflows or vanishes is reported rather than
  turned into an infinity or a zero
- [No Arbitrary-Precision Value in the Bootstrap](design/bootstrap-numbers/README.md)
  — where a number can arrive without a type, and what has to be
  written down at each of them
- [The Tuple Type](design/tuple-type/README.md) — writing down what a
  tuple is, in the shape its values are written
- [The Character Type](design/char/README.md) — what a string is made
  of, and why it is neither a byte nor a string of one
- [An Operator Where a Function Goes](design/operator-as-value/README.md)
  — writing `+⌿ v` rather than a lambda that repeats the operator
- [Where Something Is: `⍳`](design/index-of/README.md) — looking for
  something in an array or a string, and what comes back when it is
  not there
- [Whether Something Is There: `∊`](design/element-of/README.md) —
  asking only whether, which a matrix can answer where a position
  cannot
- [Equality Is `=`, Inequality `≠`](design/equality/README.md) —
  taking the glyphs back from the assignment that never used them here
- [Threading a Function Over What It Is Handed](design/listable/README.md)
  — `@listable`, and why every operator is now marked with it
- [A Hash and a Set](design/hash-and-set/README.md) — ⸨…⸩, why not
  `{ }`, and what a lookup answers when there is nothing there
- [How Many, and How Much](design/length/README.md) — `#` counts what a
  container holds and `@sizeof` measures memory, which used to be one word
- [One Type and One Unit for Everything an Array Holds](design/array-elements/README.md)
  — what a declaration says, and why a unit measures elements rather
  than the container
