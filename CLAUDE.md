Goal
====

The goal is the development of a programming language which detects many problems statically, some more dynamically, and which
allows writing code that can be reviewed easily. To do this the code is required to expose a lot more information about the
intention behind the code including adding contracts and assertions which can be used to check the state as well as creating a
human-understandable description.  This implies that the program does not exhibit undefined behavior or diverges from the actual intention.  This means any type of bug possible is caught ideally statically, ahead of time, before execution in the interpreter or during the analysis phase of the compiler.

The current specification of the language is [spec/spec.md](in this file)
while the design documentation is [ngpl.md](here).


Development Model
-----------------

The initial version of the interpreter is already available in the `interp`
directory.  It will always be meant to create the state 1 version of the
compiler.  The compiler and the full-language interpreter are written in the
NGPL language itself, the bootstrap compiler is written in Python.  The
implementation of the bootstrap part of NGPL might miss functionality and
the bootstrap version of NGPL itself might miss needed features to
implement the compiler and then the interpreter.  The bootstrap language
then needs to be extended and the Python-based interpreter be adjusted.

The compiler source code has to have a mode which only uses the bootstrap
language.  The resulting compiler need not be the best performing one and (some)
optimizations can be missing.  It is only necessary that the stage 1 compiler
can then compiler the full language.

The stage 1 compiler is used to compile the compiler sources again, producing
the state 2 compiler.  For security the stage 2 compiler than repeats the
process and produces the stage 3 compiler.  The stage 2 and stage 3 compilers
should be identical and that should be tested.

The stage 3 compiler is then used to compile the full-language interpreter and
it, as well as the stage 3 compiler, are then installed.

The source code for the compiler and the full-language interpreter should share
as much code as possible.  The code, if necessary, needs to be adjusted.  The
interpreter likely will contain most of the compiler since it is required to
just-in-time compile code during interpretation.

Since the language is not finished, especially not the bootstrap language,
it is not possible to create the compiler in first try.  Therefore the plan is
right away to start from scratch if necessary multiple times.  Old versions
are kept around.  The current source is in the subdir src of the project.


Implementation
--------------

The compiler has to be as fast as possible.  In particular, the time of
recompilation of source files with few changes is the optimization goal.
In this base optimization level all data must be collected or computed
to perform all checks, static or dynamic.

The development style should be purely functional, ideally even with function
composition and terse coding.  No global state, when possible.  Use or add
array programming primitives when useful, including combinators.  Prefer this
style of member functions but the implementation can fall back on member functions.
      
Higher optimization levels can add to compilation time, that is expected.

The compiler must use parallelism as much as possible, both data parallelism
as well as concurrency.

Contract policy: the compiler's own code uses @pre and @post wherever
possible -- a parameter's admissible range, an encoding invariant, a
result's relation to the inputs -- so that every call is checked
against what the function promises, under the interpreter today and by
the compiler's own contract machinery once it is self-hosted.  Larger
functions additionally carry assertions at their internal milestones,
assuring the results of the code so far -- parallel arrays still in
step, a resolved label no longer the sentinel, a computed offset
aligned -- so a mistake is caught where it is made rather than where
it finally crashes.  The hottest leaf helpers may prefer an assertion
in their caller over a contract of their own when the measured cost
under the interpreter demands it; the choice is recorded where it is
made.

Control flow policy: avoid if statements and other branching unless the
branch can be converted into a conditional move or a no-op.  An if that
requires a jump in the generated code should be the exception, both in the
compiler's own source and in the code it generates.  Prefer table-driven
formulations: byte-class tables, state-transition tables (DFAs), jump
tables for dense dispatch, hash tables for sparse dispatch; add such
structures to the standard runtime when they are needed.  Comparisons
should materialize values (setcc/cmov style), selections should be
computed (masking, blending, arithmetic selection), and loops should run
over data rather than over decisions.  The reason is mechanical
sympathy: code shaped this way vectorizes (SIMD) and runs on GPUs, where
divergent branches serialize execution.  Where a branch is semantically
required (short-circuit evaluation, abort paths), keep the hot path
straight-line and move the cold path out of it.

File size policy: as soon as a source file of the compiler gets too
large, split it.  Do not wait for a reason to; the size is the reason.
Split along a seam that already exists -- a section banner, a phase, an
architecture -- and cut contiguous slices so that concatenating them
reproduces the original byte for byte, which makes the split checkable:
the binaries compiled before and after must be identical on every
target.  One consequence to remember: the order of the files is part
of the program, since a unit must be declared before it is used while a
struct, a function, a global and an enum need not.  The order is not
written down anywhere outside the sources -- each file names at its
head, with @import("./other.ngpl"), what it is written against, and the
compiler is handed src/main.ngpl and finds the rest.  So a new file
says what it needs and is named by whatever needs it; build/sources.sh
holds the root file's name and nothing else.

Units policy: every variable in the NGPL source carries a unit.  A
count of bytes is ¤byte, a bare array index is ¤ptrdiff, and an index
into a table the file defines gets that table's own measure -- declared
`unit tok → ptrdiff`, which says a token index goes wherever a ptrdiff
is wanted while staying something a node id is not.  Declare the measure
that way for every table worth telling apart; something countable that
has no measure yet gets one.

A variable without a unit is the exception and says why in a
comment beside it: a bit pattern is not a quantity, a packed pair of
codes is not a count, a value read straight from a foreign structure
carries whatever that structure says.  The reason is that units are the
one check that catches a whole class of mistake the type system cannot
see -- a byte offset used as an element index has the right type and
the wrong meaning -- and the compiler's own source is the largest
program the language has to prove that on.


Process
-------

The following steps are repeated for each retry to implement the compiler.

1. take the analysis of the previous attempt of the implementation, the
   current language specification, and the current TODO lists into account
   and make a plan for the next attempt.  Plan new language features for
   the bootstrap interpreter.
2. move the current compiler sources into a new directory for archiving and
   ensure there is a new src directory.
3. implement the new bootstrap language changes
   a. update the Python implementation
   b. document the syntax and parser, point out potential problems and possible
      improvements to gain parsing speed
4. implement the next version of the compiler
   a. describe the structure of the new compiler, the functions, the data flow,
      the concurrency.  get confirmation from the user for the individual
      designs.
   b. design the internal representation of the compiler
   c. implement everything according to the plan
   d. create/adjust the compiler backend to transform the IR to binary
      code. 
   e. run the language conformance tests and fix all problems, if possible
5. analyze the compiler implementation.  If it is incomplete or otherwise
   flagged as inadequate, write the analysis to a file and continue at step 1


Limitations
-----------

The following limitations are for now acceptable:
- the compiler now generates x86-64, i386, aarch64, arm and riscv64/32
  for Linux, selected with --target (default: the host); other OSes
  will be supported later
- the ultimate goal is not to rely on existing runtime of the OS but
  instead use only the system call interface.  For the time being it is
  OK to write the compiler as a normal bimary and use existing functionlity
- the full-language interpreter will only be written once the compiler is done
  but the code structure of the compiler should allow the reuse.
