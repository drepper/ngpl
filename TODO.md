To Do List
==========

Work on all the issues without the checkmark.  Implement them on separate git branches.  Always
add test cases and adjust the language specification.  Once a to do item is complete add the
checkmark, commit the change, and change back to main.


Completed
---------

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
    deallocate all memory.  use it in main of sha256.nl instead of std.heap allocator.  After the
    sha256 call call deinit on the allocator

[x] add reset() to arena allocator — free memory but keep allocator usable.

[x] implement generic functions with apostrophe-suffixed type parameters (T', U').

[x] implement parameter packs with … suffix on the last parameter.

[x] add @sizeof(expr) intrinsic as free-function equivalent of .sizeof.

[x] implement comptime foreach for iterating over parameter packs.

[x] rewrite std.format with allocator parameter, C++ std::format-style {} fields, and array formatting.

[x] floating-point types: f16, f32, f64, bfloat, float.  IEEE 754 semantics, arithmetic operators,
    literals with decimal/hex mantissa and exponent.


Type System
-----------

[ ] arbitrary-precision floating-point type for extended precision computation.

[ ] ratio type (arbitrary-precision numerator/denominator).  Automatic decay to float when mixed
    with floating-point values.  Untyped ratio preserved at compile time.

[x] unit system: attach units (meters, seconds, bytes, count, …) to numeric types.  Enforce
    dimensional consistency: addition requires same unit, multiplication/division derive units.
    Design derived units and attribute-based annotations (e.g., radius vs diameter).

[ ] sum types (tagged unions, equivalent to std::variant).  match construct to deconstruct.

[x] product types (structs) with unspecified layout by default.  Attributes to force layout.
    @repr(C) gives a struct the platform C layout and makes .sizeof, .alignof, and
    .offsetof(name) available; without it those queries are an error rather than a guess.
    Field types without a C representation are rejected where the field is declared.

[ ] further @repr kinds beyond C: packed (no padding at all), and possibly a transparent
    single-field form.  Decide whether alignment can be raised as well as suppressed.

[ ] type aliases and user-defined cast functions (comptime, invoked in preference to builtins).

[x] add binary power operator ↑.  for integers on the left only allow integers on the right.  Ensure
    overflow and underflow are detected.

[x] to index multi-dimensional objects (matrices etc) support using multiple comma-separated
    expressions within the square brackets instead of using multiple subsequent square brackets


Data Structures
---------------

[ ] map type with literal syntax for initialized variables and member-function operations
    (insert, lookup, delete, iterate).

[ ] set type with opaque representation (bitmask, array/vector, or tree depending on attributes).
    Sets on enumerations restrict to defined values.

[ ] matrix type: 2D+ built-in data structure with arithmetic operations (multiply, transpose,
    element-wise ops).  Attributes: diagonal, upper/lower triangle, sparse.

[ ] tensor type for limited dimensionality with GPU-offloadable operations.

[ ] vector/matrix attributes: sparse, list-backed (O(n) access, stable addresses),
    tree-backed (O(log n) access).

[ ] slice/view types for arrays, matrices, and strings following Rust ownership model.


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

[ ] loop break/continue statements.  Non-local exits from nested loops.

[ ] multiple statements on one line with semicolon separator.

[ ] insecure mode scoping: per compilation-unit, function, or block (like Rust unsafe).

[ ] lazy evaluation support: lazy attribute on expressions/functions, with eager as default.
    Interaction with coroutines for opportunistic evaluation.


Functions and Combinators
-------------------------

[ ] purity enforcement: functions pure by default, impure annotation required for global
    variable access.  Strict mode disallows impure functions.

[ ] Listable/threadable attribute: functions auto-map over array/vector arguments
    (like Wolfram's Listable or APL's implicit mapping).

[ ] combinator glyphs for function composition and pipelines (APL/BQN/UIUA-inspired).
    Ranges-library equivalent for container operations.

[ ] optional monad methods: and_then, or_else, and other chaining operations on optional values.

[ ] user-defined operators with Unicode code points from mathematical operator classes.

[ ] prefix/functional form of infix operators (like Forth reverse notation or Haskell sections).


Compile-Time and Metaprogramming
---------------------------------

[ ] comptime functions: attribute to mark functions as evaluable at compile time when all
    arguments are constant.  if constexpr equivalent for conditional compilation.

[ ] hygienic macro system: expansion after scanning, before parsing.  Distinct invocation
    syntax from function calls.  Reference Rust and Common Lisp macro systems.

[ ] reflection/introspection: access to parse tree in comptime functions.  Create derived
    types and functions.  Match C++26, Rust, and Zig reflection capabilities.

[ ] function replacement: runtime replacement of @replaceable functions via compiled blobs
    with matching type signatures.  Concurrent execution support.  REPL command to override
    replaceability attribute.  (Partially implemented: @replaceable attribute exists.)


Module System
-------------

[ ] module system for composable programs and code reuse.  Name mangling with module prefix.
    Import/export declarations.  Visibility control.

[ ] multi-file compilation: compiler accepts multiple source files, build function determines
    compilation strategy.


Contract System
---------------

[ ] contracts/assertions with human-understandable descriptions.  Inspired by C++26 contracts.
    Pre/post conditions on functions.  Violations can log, terminate, or trigger debugger.

[ ] logging facility integrated into the runtime.  Callable from comptime and runtime code.
    Logging functions can terminate the program.


Memory and Lifetime Management
-------------------------------

[ ] lifetime system akin to Rust: borrow checker, ownership, move semantics.
    Stack allocation preferred for local lifetimes.  Partially started: foreach can borrow an
    array with & (read) or &mut (write through to the elements), and a mutable borrow of an
    immutable binding is rejected.  Still missing: borrows anywhere other than a foreach
    iterable, and any check that two borrows do not overlap.

[ ] reference counting for boxed values with implicit deallocation.

[x] defer statement for explicit cleanup at scope exit.  Decided against: cleanup is
    attached to the type rather than written out at each acquisition, so a value holding
    an OS resource is released when its binding's scope ends, on every exit path.
    Ownership passes on return and is not taken by parameters.  Implemented for open
    files and directories; close() releases early and makes the value unavailable.

[ ] follow resource ownership into globals, struct fields, and array elements, and release
    a resource when the binding holding it is overwritten (rebinding in a loop currently
    accumulates descriptors until the function returns).  Needs the ownership/borrow system.
    Temporaries that are never bound are already released with their statement.

[ ] address spaces: named memory regions with read/write/exec flags and access costs.
    Separate code and data address spaces.  Support for accelerator memory, cross-process
    memory, and per-thread memory regions.


Concurrency
-----------

[ ] gang concurrency: execution context pools for SIMD-like parallel execution (OpenMP-style).

[ ] job concurrency: explicitly created execution contexts for independent tasks.

[ ] coroutines: implicit support via lazy evaluation, explicit creation with type system
    representation.  Execution context pool reuse for coroutine scheduling.

[ ] communication channels: Transputer/Occam-style channels, Go-style channels.
    Mapping to OS message queues.

[ ] memory model: define shared vs private memory for threads.  Not required to follow POSIX.
    Consistent work-splitting for non-associative parallel operations.


Floating-Point
--------------

[ ] Inf/NaN handling: fault on Inf/NaN, deferred checking (check after full computation).
    Per-function or per-scope configuration.

[ ] precision improvements: Kahan summation, Veltkamp splits / Dekker multiplication,
    FMA operations.

[ ] rounding mode control: per-scope or per-function attribute, not compile-time.
    Assumption mode vs active selection.

[ ] associativity exploitation: opt-in reordering for non-bit-accurate computation.

[x] add the root functions using unary √, ∛, ∜.  only allowed for floating-point values.  Allowed
    in specification for units.


String and I/O
--------------

[ ] multi-line string literals ("""…""" syntax, possibly with " continuation prefix).

[ ] binary and hexadecimal number literal suffixes (₂ for binary, ₕ for hexadecimal).
    Also add octal literals: file modes and the S_IF* constants are conventionally
    written in octal, and std.filetype's values have to be spelled in hex without them.

[ ] format string type-specific formatting via attributes on type definitions (like Rust
    Display/Debug, Haskell Show).


Build System and Tooling
-------------------------

[ ] built-in build system: @build-annotated comptime function provides build recipe.
    Recompiled when source changes.  SBOM generation in output binary.

[ ] JIT compilation in interpreter: background compilation of hot functions, transparent
    switchover.  REPL commands to inspect generated code, machine code, and parse trees.

[ ] language server protocol (LSP) mode: expose type information, optimization decisions,
    diagnostics, and code navigation.

[x] REPL: interactive read-eval-print loop when no startup function is defined or on request.
    Define functions/variables, call functions, inspect values.  Entered via --repl, when no
    source file is given, or when the source defines no @start function.  Accepts definitions,
    statements, and bare expressions; layout blocks are terminated by an empty line.

[ ] compiler mode: ahead-of-time compilation to native code.  Startup function designation
    via command line or attribute.


Runtime
-------

[ ] native runtime using kernel interfaces directly (no libc dependency).  io_uring-based
    async I/O on Linux.

[ ] concurrency via clone3 and futex on Linux.

[ ] Vulkan code generation for GPU offloading of vector/matrix/tensor operations.

[ ] minimal runtime initialization: only pull in code for features actually used.

[ ] object file format: possibly custom format supporting partial recompilation.
    Dynamic linking support for system libraries (e.g., Vulkan shared objects).

[x] do not use camelcase for identifiers.  Change all functions in the std module to use
    underscores.  openFile was the last one; it is now open_file, with no alias kept.

[ ] add name member function (no parameters) for directory object which returns the absolute path of
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

[ ] operator precedence model: traditional precedence, APL-style right-to-left,
    or hybrid (precedence for arithmetic, flat for others).

[ ] function call delimiter: parentheses, brackets (Wolfram-style), or no delimiters (Haskell).

[ ] integer division semantics: two operators (Python), explicit cast requirement,
    or ÷ with prefix/suffix modifiers.

[ ] binary/boolean operation semantics on mixed-width integers: reject, zero-extend,
    or repeat.

[ ] attribute syntax for variables, functions, statements, blocks, and scopes.

[ ] macro invocation syntax: distinguish from function calls (Rust #[...] style, name
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
