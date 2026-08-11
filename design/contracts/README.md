# Conditions a Function Holds To

## The Question

A signature says what a function takes and what it hands back.  It has
never been able to say what has to be true for it to be asked at all,
or what it promises about the answer.  Those went in comments, which
nothing checks, or in an `assert` at the top of the body, which is
checked but is not part of what the caller reads.

This is the first piece of what the design brief calls the contract
system, and the piece the rest will be built on.

## The Shape

C++26's, which the brief names as the inspiration: `pre(cond)`, and
`post(r: cond)` naming what comes back.

Where C++26 puts them *in the signature*, these are written as
annotations before the function:

```
@pre(b ≠ 0)
@post(r: r × b = a)
fn divide(a : i64, b : i64) → i64:
    a ÷ b
```

Two reasons.  The language already puts what is said *about* a function
before it — `@impure`, `@listable`, `@noreturn`, `@test` — so a
condition in that position needs no new grammar and no new place for a
reader to look.  And a condition on a line of its own reads as the
sentence it is, which is most of what a contract is for; folded into a
signature between the parameter list and the return type, several of
them crowd the line the reader most needs to see.

More than one of each is allowed, and each stands on its own.  Two
conditions written separately say two things that must both hold, which
is what `∧` would say less legibly.

## What Each Is Read Against

A precondition is read **where the parameters are bound** — after the
arguments have been coerced to the parameter types, before the body.
So it sees the parameters as the body sees them, and it says what the
caller had to get right.

A postcondition is read **where the answer is**, after the return type
has been checked, on both the falling-off-the-end path and the early
`return`.  It may name what comes back, and it still sees the
parameters, which is what lets it relate the two: `@post(r: r = n × 2)`.

## Reported at the Condition

A violation points at the `@pre` or `@post`, not at the arithmetic in
the body that produced the offending value.

That is the whole point of writing it down.  The condition is the
sentence the programmer wrote about what should be true; showing it is
showing the claim that failed, and the reader can see at once whether
the claim or the code is wrong.  The backtrace says which call it was.

A precondition blames the caller and a postcondition blames the
function, since that is what each of them is about, and the two
messages say so in those words.

## What Is Not Here Yet

- **`old`.**  Eiffel's `old x` and Ada's `x'Old` let a postcondition
  compare against what a parameter was on entry.  That needs a copy
  taken before the body runs and a name for it; worth having, and a
  separate piece.
- **A condition on a type, rather than a function** — an invariant.
- **Choosing what a violation does.**  C++26 has ignore, observe,
  enforce and quick-enforce, chosen at build time.  Here a violation is
  always an error.  The choice is worth having once there is a build
  system to make it in.
- **Checking a condition before anything runs.**  Where the arguments
  are known at compile time, a precondition could be settled then.  The
  machinery for that is `static_assert`'s, and joining them up is its
  own piece of work.

## Status

Implemented: `@pre` and `@post` on named functions and on `impl`
methods, any number of each, with the result optionally named in a
postcondition; conditions read against the parameters and the answer;
a non-`bool` condition refused; and violations reported at the
condition with a backtrace to the call.
