# Threading a Function Over What It Is Handed: `@listable`

## The Question

`[1, 2, 3] + 10` worked, and it worked because addition carried a loop
of its own.  Seventeen lines in the evaluator looked at both operands,
noticed an array, and called the scalar operator on each element.

Everything wrong with the language's element-wise behaviour followed
from that loop being *ad hoc* rather than a rule:

- It ran **once**.  A matrix reached addition as a pair of rows and was
  refused, because the thing it called on each element was the scalar
  operator rather than the operation that had just decided to loop.
- It **zipped**.  Operands of different lengths quietly answered the
  shorter of the two, so `[1,2,3] + [10,20]` was `[11,22]`.
- It copied the element type **from an operand**, so comparing an array
  of numbers answered an array that said it held numbers and held truth
  values instead — and then refused those values the moment one was
  written back.
- It sat **below** the unit handling, so an array of lengths plus a
  length was refused, and an array of lengths plus an array of lengths
  silently threw the units away.
- It never reached **unary** operators at all, since it took two
  operands by construction.  `⁻v` was refused where `0 - v` worked.

And a user's function could not have any of it, however obviously it
wanted it.

## Considered

### A combinator — `map f v`

What Haskell and Rust do, and what this language can already write with
a lambda and a fold.  Nothing against it except where it puts the
decision: at every call, forever, for an operation whose whole point is
that it means the same thing for one thing and for many.  It also
answers nothing about the operators, which would keep their private
loops.

### At the call — Julia's `f.(v)`

Honest and explicit: the caller says *thread this*.  The objection is
the same one, moved — the reader of `double` still cannot tell whether
threading it is meaningful, and the operators still need their own
arrangement, since nobody writes `a .+ b` here.

### An operator suffix — APL's implicit mapping, or a `¨` glyph

Concise, and the array languages show it works.  But it applies to
operators and not to functions, so the language would end up with two
mechanisms — one for `+` and one for `double` — which is what it has
now and what is wrong with it.

### An attribute — chosen

Wolfram's `Listable`.  The decision sits at the definition, which is
where a reader meets the function and where the question *is this
meaningful for many?* is actually answered.

The reason to prefer it here is that it subsumes the operators.  Once
functions can be marked, the operators can be marked too, and the
seventeen lines become one mechanism that operators and functions
share.  Nothing is element-wise "as well"; `+` is listable, and that is
the whole of why `[1,2,3] + 10` works.

## The Rule

A parameter handed something **deeper than it asked for** is handed a
container of what it asked for.

Depth, not "is it an array".  What decides is the rank the parameter's
type states against the rank of the value: a parameter stating `i64` is
threaded over an `i64[]`, and a parameter stating `i64[]` is handed one
as it is and threaded only over something deeper still.  Without this a
function could not take a whole array at all, which is most of what
makes the attribute usable.

### One level at a time

Threading takes off exactly one level and asks the same question again.
That is the entire recursion: no depth is computed anywhere, and there
is no second recursive walk.  The operator dispatcher re-enters the
operator dispatcher and a call re-enters the call, so every check the
ordinary path makes — coercion, units, purity, the return type, the
backtrace frame — is made again for each element rather than once for
the container.  A matrix is met by the same question its rows are.

The consequence worth knowing is what a matrix and a vector do:

```
add([[1, 2], [3, 4]], [10, 20])     // [[11, 12], [23, 24]]
```

Rows pair against *elements*, because the outer level is taken apart
first and what is left is asked again.  This is Wolfram's answer, and
it is the only one consistent with taking one level at a time.

### Lengths must agree

There is no element to pair a leftover with.  Answering the shorter of
the two — which is what the old loop did — answers a question that was
not asked, and does it silently.

This is deliberately not NumPy.  NumPy pads and stretches shapes to
conform, which is powerful and which makes the shape of an answer
something a reader works out rather than reads.  Here nothing is
stretched: what varies together must be as long as what it varies with.

### The structure is the input's, the type is the result's

The answer has the shape of what was taken apart.  What it *holds* is
what the function answered, which need not be what it was given —
comparing numbers answers truth values, and the array says so.

That the old code got this wrong was not cosmetic.  An array tagged
`i32` holding `BoolValue`s refuses the values it already contains as
soon as one is written back, so `let r : mut = v < 2` then `r[0] ← true`
failed with *an array of i32 cannot hold a boolean*.

A listable function's return type describes **one element's** result.
Each element's call is checked against it on its own, and the caller
receives a container of them.

A signature stating no return type hands nothing back — which is what
`→ ∅` says, and why writing that draws a warning.  Threading one runs it
for each element and answers nothing, rather than collecting a row of
`∅` nobody asked for.

## What Is Refused, and Why There

Threading compares what a parameter asks for with what it is handed, so
a function that cannot answer that comparison is refused at its
definition rather than at the first call that goes wrong:

- **a by-reference parameter** — an element handed to the function is
  not a place it can write back to.
- **a parameter pack** — threading decides one position at a time, and
  a pack has no fixed positions.
- **no parameters at all** — there is nothing to thread over.

A lambda cannot carry the attribute, there being nowhere to write one;
a partly applied listable function still threads when the rest of its
arguments arrive, since it is the named function that is called in the
end.  Builtins cannot carry it either — `BuiltinFunc` has no field for
it and the standard library reaches Python methods by another path.
Both are worth revisiting.

## Comparison with Other Languages

| Language | How a function reaches the elements | Where the decision sits |
|----------|-------------------------------------|-------------------------|
| Wolfram | `Listable` attribute | the definition |
| APL, BQN | implicit for scalar functions | the language |
| NumPy | broadcasting, shapes padded to conform | the values |
| Julia | `f.(v)` | the call |
| Haskell, Rust | `map f v` | the call |
| NGPL | `@listable` | the definition |

## Status

Implemented: on named functions and on methods in an `impl` block, for
any number of parameters, at any depth, with the answer taking the
structure of what was taken apart; and on every arithmetic, comparison,
logic, shift and saturating operator, unary and binary alike, which is
now the whole of why any of them is element-wise.

`⧺`, `⍳`, and `∊` are deliberately not listable: each takes a container
*as* its operand rather than as a stand-in for the things in it.  They
are dispatched before threading can see them, so the two statements
cannot drift apart.
