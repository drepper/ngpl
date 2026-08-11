# Functions That Do Not Come Back

## The Question

`std.exit(0)` ends the program, and the line after it was as reachable
as any other as far as the language was concerned.  So was the line
after a wrapper that called it — `quit_early()` and then a `println`
that would never run, with a comment beside it saying so, because the
comment was the only thing that could.

A signature says what a function takes and what it hands back.  It had
no way to say that it hands back *nothing, ever*.

## The Attribute

`@noreturn`, on a function whose body does not come back.

It is worth having only because of what it enables at the *call* site.
A `return` already makes what follows it unreachable, and that needs no
attribute — the statement is right there to see.  A call does not: the
reader of `die("stop")` cannot tell from the call whether the next line
runs, and neither could the checker.  `@noreturn` is the one thing that
can say so, and saying it once at the definition says it at every call.

The test suite had an example of exactly this already: an output test
whose program calls a wrapper around `std.exit` and then prints, with
`// also unreachable` beside the print.  The checker now says it, and
would not have without the attribute.

## The Standard Library

`std.exit` and `std.abort` are the two the language has, and neither
can carry the attribute: they are Python methods on the standard
library object, not functions the language declares.  They are named in
the checker instead.

That is a small piece of hard-coding and worth being honest about: the
list stands in for an annotation the library cannot yet write.  It is
two names and both are termination — if a third arrives that is not,
the mechanism should grow rather than the list.

## What It Refuses

Stating a return type says what the caller receives; `@noreturn` says
the caller receives nothing, because it is never reached again.  Both
at once is a contradiction and is refused at the definition.

## What It Does Not Check

A `@noreturn` function whose body falls off the end is not reported.
Knowing that in general is the halting problem in a hat: a body ending
in `while true:` never comes back, and a body ending in an `if` whose
arms both die never comes back, and telling those from a body that
simply forgot is not something a syntactic pass can do without either
false positives or a flow analysis the interpreter does not have.

So the attribute is taken on trust, which is the honest description of
what C does too.  Rust and Zig do better by making it a *type* — `!`
and `noreturn` — which the type checker verifies rather than believes.
That is the answer to move to when the type system can carry it, and an
attribute is the shape that migrates most easily into one.

## Only the First of a Run

Three statements after a call that does not come back are three
unreachable statements, and reporting all three says the same thing
three times.  The first is reported; the rest are unreachable for the
same reason.

## Status

Implemented: the attribute on named functions and on `impl` methods;
`std.exit` and `std.abort` treated as having it; the unreachable-
statement warning after both those and after a `return`, reported at
the statement that cannot be reached; and the return-type contradiction
refused at the definition.
