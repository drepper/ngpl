To Do List
==========

Work on all the issues without the checkmark.  Implement them on separate git branches.  Always
add test cases and adjust the language specification.  Once a to do item is complete add the
checkmark, commit the change, and change back to main.


The Bootstrap Language and the Full Language
--------------------------------------------

The Python interpreter in `interp/` is the **bootstrap implementation**.  What it accepts is the
**bootstrap language**, which is a strict subset of the full language that `spec/ngpl.md`
specifies.  The subset is defined by the implementation: a feature is in the bootstrap language
when `interp/` implements it, and belongs to the full language until then.

A bootstrap exists to be small enough to write by hand and to carry a self-hosting compiler far
enough to take over.  It does not need every feature, and paying for the ones it does not need
would defeat the point of having one.

Two rules hold:

- The subset is strict.  A program the bootstrap accepts means the same thing in the full
  language.  The bootstrap never accepts what the full language rejects, and never gives an
  accepted program a different meaning.
- A feature outside the subset is refused rather than ignored.  Using one is an error naming the
  feature, so a program that runs is one the full language would run the same way.

An outstanding item tagged `[FULL]` is part of the full language and not yet part of the
bootstrap.  When it is implemented the tag goes with the checkmark, and the feature has crossed
into the bootstrap language.  The boundary only moves that way; nothing leaves the bootstrap once
it is in.

An outstanding item with no tag is not a missing feature but a gap in one the bootstrap already
has: something it accepts that it should refuse, or reports less well than it should.  Those are
corrections rather than crossings, so no tag travels with the checkmark.

`spec/ngpl.md` marks the same boundary from the other side, so a section describing a feature the
bootstrap does not have says so.

### Already Refused

`int` and `float`, the arbitrary-precision types, are full-language only.  A variable, parameter,
return type, struct field, or type alias naming one is an error in the bootstrap:

    let n : int = 5

    error: 'n': 'int' is an arbitrary-precision type, which the bootstrap
    implementation does not provide; use a sized type such as i64

An *untyped* literal is unaffected.  It is arbitrary-precision while it is being computed with and
settles on the type it is used at, so `let n := 5` and `1 « 40` are both fine.  What the bootstrap
does not provide is a variable that stays arbitrary-precision, since that needs a representation
the sized types do not have.


Completed
---------

[x] a static diagnostic points at what it objected to.  A check answers with the node it
    found as well as the message, DefinitionError carries the position, and the result is
    rendered with the same excerpt and caret a runtime error gets — in a file and at the
    prompt alike.  Definitions that had no position now carry one, so the errors raised
    while installing them are located too.

[x] a type without brackets names a scalar, so an array meeting one is refused rather
    than read as a shorthand for what its elements are.  The rule holds at a binding, a
    parameter, and a return type.  Where the body writes the array out, the signature and
    the brackets settle it between them and it is reported at the definition rather than
    when the function runs.  sha256.ngpl declared its eight-word hash state u32 and
    nothing said so; it is u32[8].

[x] division is written ÷ rather than /, as multiplication is written × rather than *.
    A slash is not an operator; it keeps only the comment openings // and /*, and one
    used as division says so rather than being read as the start of a comment.  The
    division sign is what a unit formula uses and what a derived unit displays, so a
    speed is declared ¤meter÷second and prints as m÷s.

[x] approximate comparisons for floating-point values: ≅ ≇ ⪅ ⪆ ⪉ ⪊ against == != <= >= < >,
    to within std.comparison_tolerance, which follows APL's ⎕CT in being a fraction of the
    larger operand rather than an absolute epsilon.  Scoping the tolerance is still open.

[x] check a struct-typed parameter at the call, and a binding declared with a struct type,
    so the wrong struct is reported where it is passed rather than at the first field that
    turns out to be missing.

[x] @min and @max giving the extreme values a numeric type can hold, as C++'s
    numeric_limits max() and lowest() do.  Invalid for anything else.

[x] integer types of any stated bit width (i7, u13, u1, i128), with the range, wrapping,
    shift bound, and storage all following from the width.

[x] sum types (tagged unions, equivalent to std::variant).  match construct to deconstruct.

[x] allow lambda functions to have bodies of multiple statement.  Indicate using the usual syntax of
    colon at the end of { } block.

[x] add @enumerate(CONTAINER) which creates an iterator that can be used as in
    foreach i,v := @enumerate([5,4,3,2,1]):

[x] add static_assert, static_assert_eq etc to force the contained tests to be performed at compile time.
    If the expression is not compile-time constant raise a compilation error/crash the interpreter.
    add tests

[x] add @typeof(EXPR) and @resultof(FCT).  These builtin functions return types which can be tested for
    equality with other types.  Use it in examples using static_assert_eq etc.  Depends on static_assert.

[x] Add operators for left and right fold.  The first parameter is a function, the second the
    container, the third the start value.  Choose glyphs, document, test.  Update the sha256 to use
    left fold to compute the return value.

[x] add support for currying function and test it.  Create functions and in a new function curry them
    and then use the result in calls to generate.  Repeat the same with lambda functions.  Document
    the language changes.

[x] implement arena allocators in std.  Provide std.arena.allocator() to get an arena allocator
    with the usual alloc member etc.  Also provide a deinit member function which can be used to
    deallocate all memory.  use it in main of sha256.ngpl instead of std.heap allocator.  After the
    sha256 call call deinit on the allocator

[x] add reset() to arena allocator — free memory but keep allocator usable.

[x] implement generic functions with apostrophe-suffixed type parameters (T', U').

[x] implement parameter packs with … suffix on the last parameter.

[x] add @sizeof(expr) intrinsic as free-function equivalent of .sizeof.

[x] implement comptime foreach for iterating over parameter packs.

[x] rewrite std.format with allocator parameter, C++ std::format-style {} fields, and array formatting.

[x] std.print takes a format string first, as C++'s std::print does, and reads the same
    replacement fields std.format reads.  The specifier is the full C++ grammar —
    fill, align, sign, #, 0, width, precision, presentation type — with two flags of
    NGPL's own for what an NGPL value carries and a C++ value does not: t writes the
    type suffix, u leaves the unit off.  Neither is on by default, so a number is
    written without its width and a measured value with its unit.

[x] floating-point types: f16, f32, f64, bfloat16, float.  IEEE 754 semantics, arithmetic operators,
    literals with decimal/hex mantissa and exponent.


Type System
-----------

[ ] [FULL] arbitrary-precision floating-point type for extended precision computation.

[ ] [FULL] ratio type (arbitrary-precision numerator/denominator).  Automatic decay to float when mixed
    with floating-point values.  Untyped ratio preserved at compile time.

[x] unit system: attach units (meters, seconds, bytes, count, …) to numeric types.  Enforce
    dimensional consistency: addition requires same unit, multiplication/division derive units.
    Design derived units and attribute-based annotations (e.g., radius vs diameter).


[x] product types (structs) with unspecified layout by default.  Attributes to force layout.
    @repr(C) gives a struct the platform C layout and makes .sizeof, .alignof, and
    .offsetof(name) available; without it those queries are an error rather than a guess.
    Field types without a C representation are rejected where the field is declared.

[ ] [FULL] further @repr kinds beyond C: packed (no padding at all), and possibly a transparent
    single-field form.  Decide whether alignment can be raised as well as suppressed.

[ ] [FULL] type aliases and user-defined cast functions (comptime, invoked in preference to builtins).

[x] add binary power operator ↑.  for integers on the left only allow integers on the right.  Ensure
    overflow and underflow are detected.

[x] to index multi-dimensional objects (matrices etc) support using multiple comma-separated
    expressions within the square brackets instead of using multiple subsequent square brackets


Data Structures
---------------

[ ] [FULL] map type with literal syntax for initialized variables and member-function operations
    (insert, lookup, delete, iterate).

[ ] [FULL] set type with opaque representation (bitmask, array/vector, or tree depending on attributes).
    Sets on enumerations restrict to defined values.

[ ] [FULL] matrix type: 2D+ built-in data structure with arithmetic operations (multiply, transpose,
    element-wise ops).  Attributes: diagonal, upper/lower triangle, sparse.

[ ] [FULL] tensor type for limited dimensionality with GPU-offloadable operations.

[ ] [FULL] vector/matrix attributes: sparse, list-backed (O(n) access, stable addresses),
    tree-backed (O(log n) access).

[ ] [FULL] slice/view types for arrays, matrices, and strings following Rust ownership model.


Control Flow and Expressions
-----------------------------

[x] match statement for deconstructing sum types and optionals.  Done for optionals and
    results: ∃(name) binds a present value or a success, ∄(name) binds a failure's error,
    ∅ matches absence, _ matches the rest, and a value no arm accepts is an error.
    ∄(e) is also an expression, which is how a function originates an error rather than
    propagating one.  Sum types will use the same statement.  Exhaustiveness is checked
    where the subject's type can be worked out -- a call with a declared return type,
    division, a written-out ∃/∅/∄, or a builtin optional-returning method -- and at run
    time otherwise; it will reach further as type inference grows.

[ ] [FULL] loop break/continue statements.  Non-local exits from nested loops.

[ ] [FULL] multiple statements on one line with semicolon separator.

[ ] [FULL] insecure mode scoping: per compilation-unit, function, or block (like Rust unsafe).

[ ] [FULL] lazy evaluation support: lazy attribute on expressions/functions, with eager as default.
    Interaction with coroutines for opportunistic evaluation.


Functions and Combinators
-------------------------

[ ] [FULL] purity enforcement: functions pure by default, impure annotation required for global
    variable access.  Strict mode disallows impure functions.

[ ] [FULL] Listable/threadable attribute: functions auto-map over array/vector arguments
    (like Wolfram's Listable or APL's implicit mapping).

[ ] [FULL] combinator glyphs for function composition and pipelines (APL/BQN/UIUA-inspired).
    Ranges-library equivalent for container operations.

[ ] [FULL] optional monad methods: and_then, or_else, and other chaining operations on optional values.

[ ] [FULL] user-defined operators with Unicode code points from mathematical operator classes.

[ ] [FULL] prefix/functional form of infix operators (like Forth reverse notation or Haskell sections).


Compile-Time and Metaprogramming
---------------------------------

[ ] [FULL] comptime functions: attribute to mark functions as evaluable at compile time when all
    arguments are constant.  if constexpr equivalent for conditional compilation.

[ ] [FULL] hygienic macro system: expansion after scanning, before parsing.  Distinct invocation
    syntax from function calls.  Reference Rust and Common Lisp macro systems.

[ ] [FULL] reflection/introspection: access to parse tree in comptime functions.  Create derived
    types and functions.  Match C++26, Rust, and Zig reflection capabilities.

[ ] [FULL] function replacement: runtime replacement of @replaceable functions via compiled blobs
    with matching type signatures.  Concurrent execution support.  REPL command to override
    replaceability attribute.  (Partially implemented: @replaceable attribute exists.)


Module System
-------------

[ ] [FULL] module system for composable programs and code reuse.  Name mangling with module prefix.
    Import/export declarations.  Visibility control.

[ ] [FULL] multi-file compilation: compiler accepts multiple source files, build function determines
    compilation strategy.


Contract System
---------------

[ ] [FULL] contracts/assertions with human-understandable descriptions.  Inspired by C++26 contracts.
    Pre/post conditions on functions.  Violations can log, terminate, or trigger debugger.

[ ] [FULL] logging facility integrated into the runtime.  Callable from comptime and runtime code.
    Logging functions can terminate the program.


Memory and Lifetime Management
-------------------------------

[ ] [FULL] lifetime system akin to Rust: borrow checker, ownership, move semantics.
    Stack allocation preferred for local lifetimes.  Partially started: foreach can borrow an
    array with & (read) or &mut (write through to the elements), and a mutable borrow of an
    immutable binding is rejected.  Still missing: borrows anywhere other than a foreach
    iterable, and any check that two borrows do not overlap.

[ ] [FULL] reference counting for boxed values with implicit deallocation.

[x] defer statement for explicit cleanup at scope exit.  Decided against: cleanup is
    attached to the type rather than written out at each acquisition, so a value holding
    an OS resource is released when its binding's scope ends, on every exit path.
    Ownership passes on return and is not taken by parameters.  Implemented for open
    files and directories; close() releases early and makes the value unavailable.

[ ] [FULL] follow resource ownership into globals, struct fields, and array elements, and release
    a resource when the binding holding it is overwritten (rebinding in a loop currently
    accumulates descriptors until the function returns).  Needs the ownership/borrow system.
    Temporaries that are never bound are already released with their statement.

[ ] [FULL] address spaces: named memory regions with read/write/exec flags and access costs.
    Separate code and data address spaces.  Support for accelerator memory, cross-process
    memory, and per-thread memory regions.


Concurrency
-----------

[ ] [FULL] gang concurrency: execution context pools for SIMD-like parallel execution (OpenMP-style).

[ ] [FULL] job concurrency: explicitly created execution contexts for independent tasks.

[ ] [FULL] coroutines: implicit support via lazy evaluation, explicit creation with type system
    representation.  Execution context pool reuse for coroutine scheduling.

[ ] [FULL] communication channels: Transputer/Occam-style channels, Go-style channels.
    Mapping to OS message queues.

[ ] [FULL] memory model: define shared vs private memory for threads.  Not required to follow POSIX.
    Consistent work-splitting for non-associative parallel operations.


Floating-Point
--------------

[ ] [FULL] Inf/NaN handling: fault on Inf/NaN, deferred checking (check after full computation).
    Per-function or per-scope configuration.

[ ] [FULL] precision improvements: Kahan summation, Veltkamp splits / Dekker multiplication,
    FMA operations.

[ ] [FULL] rounding mode control: per-scope or per-function attribute, not compile-time.
    Assumption mode vs active selection.

[ ] [FULL] associativity exploitation: opt-in reordering for non-bit-accurate computation.

[x] add the root functions using unary √, ∛, ∜.  only allowed for floating-point values.  Allowed
    in specification for units.


String and I/O
--------------

[ ] [FULL] multi-line string literals ("""…""" syntax, possibly with " continuation prefix).

[ ] [FULL] binary and hexadecimal number literal suffixes (₂ for binary, ₕ for hexadecimal).
    Also add octal literals: file modes and the S_IF* constants are conventionally
    written in octal, and std.filetype's values have to be spelled in hex without them.

[ ] [FULL] format string type-specific formatting via attributes on type definitions (like Rust
    Display/Debug, Haskell Show).

[ ] a std.print call whose first argument is a literal of the wrong kind — std.print(42) — is
    settled by reading it, so it should be reported at parse time rather than when the branch
    holding it runs.  The same holds for a template whose field count does not match the number
    of arguments after it, where both are written down.  The static diagnostic now carries a
    source position, so the check can move without losing the caret.


Build System and Tooling
-------------------------

[ ] a struct field's diagnostic points at the struct rather than at the field, since a field
    is a (name, type) pair with no position of its own.  Carrying one would change the shape
    the layout and struct-type code reads.

[ ] [FULL] built-in build system: @build-annotated comptime function provides build recipe.
    Recompiled when source changes.  SBOM generation in output binary.

[ ] [FULL] JIT compilation in interpreter: background compilation of hot functions, transparent
    switchover.  REPL commands to inspect generated code, machine code, and parse trees.

[ ] [FULL] language server protocol (LSP) mode: expose type information, optimization decisions,
    diagnostics, and code navigation.

[x] REPL: interactive read-eval-print loop when no startup function is defined or on request.
    Define functions/variables, call functions, inspect values.  Entered via --repl, when no
    source file is given, or when the source defines no @start function.  Accepts definitions,
    statements, and bare expressions; layout blocks are terminated by an empty line.

[ ] [FULL] compiler mode: ahead-of-time compilation to native code.  Startup function designation
    via command line or attribute.


Runtime
-------

[ ] [FULL] native runtime using kernel interfaces directly (no libc dependency).  io_uring-based
    async I/O on Linux.

[ ] [FULL] concurrency via clone3 and futex on Linux.

[ ] [FULL] Vulkan code generation for GPU offloading of vector/matrix/tensor operations.

[ ] [FULL] minimal runtime initialization: only pull in code for features actually used.

[ ] [FULL] object file format: possibly custom format supporting partial recompilation.
    Dynamic linking support for system libraries (e.g., Vulkan shared objects).

[x] do not use camelcase for identifiers.  Change all functions in the std module to use
    underscores.  openFile was the last one; it is now open_file, with no alias kept.

[ ] [FULL] add name member function (no parameters) for directory object which returns the absolute path of
    the directory.

[x] exit function to terminate the process with the exit code given as argument.  std.exit(code)
    takes 0…255 and rejects anything outside it rather than truncating; it wins over the @start
    function's return value and produces no diagnostic or backtrace.

[x] abort function to terminate the process with the signal given as argument (if no signal is
    given or it is zero or invalid, use SIGABRT).  std.abort(signal) resets the handler to the
    default first so the parent sees the termination signal, and prints a backtrace before dying.

[x] add backtrace support.  when the program exits abnormally show the call stack of functions of
    the program (not the interpreter).  Add also API in the std module to access the callstack
    at any time.  Frames carry the position execution had reached, the stack travels with the
    failure so it cannot be reported against the wrong error, and std.callstack() returns
    (name, line, column) tuples innermost first.


Syntax Decisions Still Open
----------------------------

[ ] [FULL] operator precedence model: traditional precedence, APL-style right-to-left,
    or hybrid (precedence for arithmetic, flat for others).

[ ] [FULL] function call delimiter: parentheses, brackets (Wolfram-style), or no delimiters (Haskell).

[ ] [FULL] integer division semantics: a second operator alongside ÷ (as Python has //),
    an explicit cast requirement, or a modifier on ÷ saying which rounding is meant.

[ ] [FULL] binary/boolean operation semantics on mixed-width integers: reject, zero-extend,
    or repeat.

[ ] [FULL] attribute syntax for variables, functions, statements, blocks, and scopes.

[ ] [FULL] macro invocation syntax: distinguish from function calls (Rust #[...] style, name
    annotation, or different parameter delimiters).

System Environment
------------------

[x] provide access to the command line parameters of the program through a std.args submodule
    with program(), count(), get(i), and all().  The program name is kept out of the parameter
    list.  The interpreter passes everything after a -- separator to the program.

[x] provide read access to the environment of the process through std.env with get() returning
    an optional (so an empty value stays distinct from an unset one), has(), count(), names().

[x] provide access to CPU affinity mask and derived from this number of CPUs to use.
    Also provide access to total number of CPUs, total memory.  Implemented as std.sys with
    affinity(), affinity_cpus(), usable_cpus(), online_cpus(), total_cpus(), page_size(),
    and total_memory().
