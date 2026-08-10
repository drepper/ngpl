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
