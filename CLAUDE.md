Goal
====

The goal is the development of a programming language which detects many problems statically, some
more dynamically, and which allows writing code that can be reviewed easily.  To do this the code
is required to expose a lot more information about the intention behind the code including adding
contracts and assertions which can be used to check the state as well as creating a human-understandable
description.

Required features:

- it is interpreted, JITed in the interpreter, and ahead-of-time compiled
- can be used for scripting by requiring little static information to be available by using boxed values if necessary
- but when the programmer provides additional information in the form of type information, annotations, and other useful information, the program can be executed and/or compiled efficiently
  - humans need to be able to provide all the information for best operation in a manageable fashion
  - this does not preclude that the language allows possibly very complicated and voluminous annotations
    which is something that automatically generated code can easily contain.  There is no limit on the
    types of input accepted as long as it provides a benefit
- in a strict mode
  - all type information must be discoverable at compile-time (Hendley-Milner or similar). If a type is a sum
    type, this is OK. When the value is used without resolving the actual type a (possibly inlined) dispatcher
    version of the called function is created which calls the referenced function with the actual realized type.
  - variables need unit information like count, seconds, bytes, meters and all arithmetic, container use, etc must follow the rules
    - operations like addition need the same unit for all inputs
    - operations like multiplication and division create appropriately derived units
    - containers like arrays require all elements to have the same unit
- Integer types with arbitrary bit count.  There should be at least support for 16, 32,
  and 64-bit IEEE floating-point.  For specific targets the `bfloat16` data type should be available as well.
  Additionally, there should be an arbitrary precision floating-point type and a data type for ratios.  The
  latter should automatically decay to a floating-point value in computations involving a floating-point
  value. Names should be short, suggesting i1, i16, u32, f16, f32, f64.  Use bfloat16 and bool.
- in addition to the arithmetic operation defined on all numbers, the language also defines binary logic
  and boolean operations on integers.  The latter are guaranteed to only create values 0 and 1.
- expressions as in all languages with infix operators need grouping and `(` and `)` are used.
- assignments and variable definitions with initialization have different syntax.  Definitions use a keyword
  (e.g. `var`) followed by the name, followed by a colon, followed by an optional type, followed by either an equal sign
  and an expression or complex initializer enclosed in `{` and `}`.  This is a mixture between Odin's and
  C++'s definition.  An assignment use `←` as the operator between
  the name of the left and the value on the right.
- if the function call syntax needs delimiters at all, would it be better to follow Wolfram and use
  `[` and `]` instead of `(` and `)` and leave the latter exclusively to expression grouping?  Ideally
  no delimiters are needed as in Haskell.
- function calls without the required number of arguments automatically currys the function.
- the language should allow everything to be performed in a functional way and without side-effects.
  Functions should be composable and first rate objects.  The use of combinators should be simple and the
  most common ones should be defined.  Languages like APL, BQN, UIUA should serve as examples but at the
  same time aspects like currying should be possible as in Haskell.
- functions are by default pure.  In case a function has to access a non-constant global variable it must
  be declared impure.  If the compilation unit is compiled is strict this is not possible.
- functions should be able to thread over one or more dimensional objects.  This can be implemented using a
  function attribute like `Listable` in Wolfram or using an operator prefix/suffix like `/` in APL for `+/`
  denotating summation of the elements of the argument vector.
- the optional monad is part of the language and special syntax for its use (as also present in Rust, Zig,
  and other modern languages) is available.  E.g., the `?` (perhaps different syntax) to unpack the optional
  and fail if it's empty.  The optional object also has functions operating on it like `and_then` and `or_else`
  and possibly more.  Perhaps use a syntax like a `!` prefix or suffix to unpack and abort in case the optional is empty.
  Instead of using in the language ASCII characters use Unicode glyphs like ⍰ and ⚠ and allow per-compile-unit
  replacements such as ? and ! to be defined using macros.
- Arithmetic sum and product sizes are present.  The sum type is the equivalent of `std::variant`, not
  `union` in C++.  Possibly introduce a `match` language construct to deconstruct the value.  Product types by default
  have no layout defined.  The compiler and interpreter can feel free to rearrange elements and add or avoid
  padding.  Attributes for types to force predictable layout (possibly matching other language implementations)
  must be available.  Define default layout defined.
- array and matrix variables can be accessed with an index value between or `[` and `]` or `⟦` and `⟧`.
  If there are other places where `[` and `]` are needed to simplify the syntax, use `⟦` etc.
- enumeration are available with attributes controlling the default value allocation.
  A flag attribute specifies the automatic values are powers of two.  Enums
  of this type have binary logic operations to combine values defined and 
  a `nil` name, if no value for zero is defined.  The actual size of the type used can be controlled in a
  similar way to C++ `enum class` objects.  The names of the enums are not in the global namespace and
  must be specified along with the enum's name (and possibly the module's name).
- a map type is also part of the language with appropriate syntax to create initialized variables.  The
  operations on the map objects need to be available as (member) function calls.  Optionally convenience
  syntax like `[…]` or `⟦…⟧` can be defined per macros on a per-compile-unit-basis.
- a set type with an opaque representation is available.  A representation as a bitmask is preferred but
  it can be wasteful. Alternatives are arrays/vectors or even trees.  A set on an enumeration only allows
  the values defined.  A set type for integers could be annotated with an attribute which hints at the
  number of set elements to guide the selection of the representation.  Many elements suggests a higher
  limit of the bitset size.
- the language does not use garbage collection.  It must use explicit lifetime handling akin to the Rust
  language or use boxed values with reference counting and implicit deallocation.  The allocation on the
  stack is preferred if the lifetime of the object is determined to be local and the system is not declared
  to have a limited stack size.
- while the language is general purpose, special attention is paid to arithmetic on vectors, matrixes,
  and tensors of limited dimensionality. Code generation should also include targets like Vulkan for
  execution on GPUs, with programs on the CPU using offloading to the GPU.  Vectors, matrixes etc are
  built-in data structures, both fixed-sized and dynamically sized.
- dynamically vectors (1-dimensional) can have attributes to indicate that they are OK with O(n) random
  access and be implemented as lists.  Possibly also allow implementation with O(log(N)) for balanced
  trees.  A list's elements have stable addresses which might be necessary.  All vectors and matrixes
  can have a sparse attribute which also changes the random access time but reduces memory consumption.
  Matrixes can also have attributes diagonal, upper (triangle), lower (triangle), and possibly other
  attributes.  Allow the underlying type vectors and matrixes to be all integer, floating-point and
  bool type.  Optimize bool type unless an view attribute is attached.  A vector with element type
  other than those specified above does not have the arithmetic attribute which allows using values
  of this type to be used with vector/matrix arithmetic operators and functions.  Without the arithmetic
  attribute the objects can only be used for storage, random access, and iterating.
- to facilitate high-performance computation (especially when offloading) the operations on vectors etc
  must be performed using operators on the entire data structures.  The
- a string type using UTF-8 is also built into the language and operators on string values available at
  compile-time create another string available at compile-time.
- for vectors, matrices, strings etc appropriate slice/view types are available to get create appropriate
  slices.  Ownership etc follows the Rust model.
- there must be a module system to write larger, composable programs and facilitate code reuse.
  Function and variable names get in the mangled representation is prefix or postfix with the module
  name.
- one of the main aspects of the language is a way to create human-understandable descriptions of
  assertions and conditions the program is supposed to fulfill.  Possible inspirations are the
  contract system in C++26.  The same functionality should also allow logging and an internal
  logging facility has to be implemented in the runtime.
- there should be a concept of address spaces in the language.  An execution context would have access
  to one or more address spaces.  Accesses to different address spaces can have different costs which
  can be defined.  Examples are accesses to memory on accelerators or access to memory in different
  processes, possibly on different machines.  Address spaces should have names as well as a possible
  indication of a version.  E.g., memory of different accelerators might have different names.  Each
  thread/process might run the same code but have different copies of the same code or data.  Address
  spaces have attributes like read, write, exec flags, access costs, etc.
- in the context of address spaces, it might be useful to have all the code of a program in a address
  space different from data.  That address space should not allow writing, it might even be useful to
  not even allow reading, just use of pointers/references for execution.
- support for concurrency on the CPU is needed, both in the form for gangs (same code executed with
  different inputs, somewhat in lock-step) as well as well as jobs.  The use case should be made explicit
  and possibly different implementations can be used.  For gangs it might be useful to create pools of
  execution contexts (similar to OpenMP concurrency) while for jobs explicitly created contexts might
  be better.  The execution context creation might also create address spaces.  This would, for instance,
  allow a simpler implementation of the equivalent of thread-local storage since the memory is in the
  same address in all threads.  This will require a different thread model from POSIX: neither is all
  memory private nor is everything shared.
- there should also be support for co-routines.  This should be at least implicitly supported when
  using appropriately marked lazy computation or when creating pipelines for computations and the
  computation needs to create intermediate results.  Explicit co-routine creation and the representation
  in the type system might be needed, too.
- to facilitate concurrency it might be useful to define communication channels, similar to the
  communication facilities in the Transputer processors and the Occam language used on them, and also
  similar to Go language.  Mapping to facilities like message queues (as implemented in some OSes) should
  be implemented.  There might also be some support in processors.
- floating-point support and the limitations associated with it are of central importance.  Bit-accurate
  results might be needed sometimes but not always.  In the latter case associativity of the operations
  might be exploited.  It might also be useful to fault on Inf/Nan, perhaps and possibly preferred in a
  deferred way.  E.g., an entire summation might be performed before a single check for Inf/NaN on the
  final result is performed.  The language should provide ways to specify and/or indicate the behavior
  (perhaps dynamically selected at runtime), for individual computations or for function.  The latter
  can then be used by the optimizer to simplify code optimization.  Support for unreliable floating-point
  execution such as the legacy 80-bit formation on x87 FPU is not supported.  On the other hand,
  improvements of precision can be requested:
  - Cahan algorithm for sums etc
  - Veltkamp splits for increased precision data types with Dekker multiplication etc
  - use of FMA operations
  - support for arbitrary precision rational and floating-point numbers
  - support for rounding mode as attribute for library functions (not compile time).  Specify rounding
    mode etc for scopes or entire functions, as assumption or active selection, and call appropriate
    library function.
- the encoding of the source code files mandatorily must be UTF-8 or a UCS variant.  Running the
  interpreter or compiler in a locale (a concept not yet designed for the language itself) results
  in a fatal error right at startup.  The use of Unicode glyphs for operators (as in APL, BQN, UIUA)
  as well as possibly integrating glyphs into the syntax/scanner/parser to facilitate faster/easier
  source code handling and compact programmer-provided additional information is definitely envisioned.
- the language provides support something for like `comptime` in Zig and `if constexpr` in C++.  Calls to
  the logging functions of the language are allowed as well as every operation that can be performed
  at compile-time.  Compilation failures are reported if non-`constexpr` functions, when using the C++
  nomenclature, are called.  One of the interface functions of the logging functionality should
  allow to terminate the program.  Entire functions can have the attribute `comptime`/`constexpr` in
  which case the function can be evaluated at runtime when all arguments are available at compilation
  time.
- unlike in Python, no code can be defined outside a function.  In the interactive read-eval-print-loop
  of the interpreter function calls can be issued in additional to new function and variables being
  defined as well as variable values printed and changed.
- when generating programs, exactly one function must be designated as the startup function with an
  appropriate attribute or a flag on the compiler command line (which can have a default value).  The
  prevalence is 1. explicit command line argument, 2. attribute in code, 3. default command line argument.
- unit test support is built in, similar to Rust etc.  Annotate a function as a test.  Possibly reference
  one or more functions in the file.  Code for the test functions are added to the binary unless test results
  are marked skipped for production code.  A program can start in test mode which performs all the tests
  and then terminates with an appropriate status.  Unless tests are skipped, tests are run when the program
  runs.  Test functions that do not reference one or more specific functions run at startup before the
  startup function. Tests that do reference functions implemented in the compilation unit are run when
  and of the referenced functions is called (like `pthread_once` in POSIX threads).  Test functions 
- a build system should be built into the compiler.  One function indicated with and appropriate attribute
  or through a command line argument (same precedence as for the designation of the startup function) is
  consulted for the build receipe. The function must be `comptime`-declared.  Arithmetic and string operations
  on constants are allowed.  Some special functions avilable in the build mode can be used in the build
  function.  The function when the compiler is finished is meant to be translated into executable code and
  then run.  It is recompiled if the source of the build function definition in the source code is changed.
  In the first incomplete version of the compile environment the interpreter can be used.  The entire
  concept is matching Zig's build system.  The goal is to include in the generate binary all the information
  necessary to identify every source and the version (a SBOM).
- there has to be a concise syntax for explicit casts which at the same time is context free.  Cast functions
  for types can be defined by the user and are invoked in preference to implementation-defined versions.
  Cast functions must be declared `comptime`.  If no user-defined cast and no built-in cast is defined this
  is a compile error.  Potential syntax might follow Zig.
- the syntax should allow combining multiple statements in one line with an appropriate separator like a
  semicolon in many languages.  Block delimination could be similar to Haskell or Python3 (no mix of space/tab
  prefixes) or requirement end markers.  Function return values should not need a keyword like `return` unless
  it is an early return.
- comments should be available for lines and blocks, like // and /* … */ in C++.
- string constants have escape mechnisms to encode invisible characters like bells, newlines etc or a
  string delimiter.  Simple strings cannot contain a newline character, a string constant must end before
  the end of the line in the source code.  An equivalent to """…""" strings in Python can be added and
  these can allow multiple lines.  Possibly require each continuation line to start with a character like
  " to allow for indentation of the content without affecting the content of the string and to quickly
  test that the newline is actually wanted.
- number constants must allow a notation in binary, decimal, and hexadecimal form.  This includes the
  floating-point numbers where the exponent and mantisse can use different bases.  Potentially use
  suffixes like ₂ and ₕ for binary and hexadecimal, defaulting to decimal with no suffix.
- A hygienic macro system is built in.  Possible reference are the Rust and Common Lisp macro systems.
  The macro expansion happens just after scanning the relevant text and before any further processing.
  When explictly using macros, the invocation looks different from a normal function call to make
  the difference visible.
- Reflection/introspection provides access to the parse tree and allows, in comptime functions, to create derived
  or new language objects which then can be installed or instantiated.  The functionality is (mostly)
  part of the language.  This is different from the C++26 implementation but the functionality should
  include everything the C++26 and also Rust and Zig provide.
- Function replacement with introspectation and possibly an explicit eval function (like in Swift) code
  for a new function can be created.  The type of the binary blob must contain the type signature of
  the function.  Assigning the blob reference to a function name with the same type signature allows
  the implementation to be replaced.  A function needs to have an appropriate attribute to allow
  replacement, the default is off.  Replaceble function might need to be placed in different memory
  regions which do not have memory protection activated.  Ideally concurrent execution is possible.
  An implementation redirects execution with a jump in the first instruction of the original code.
  In the interpreter this is much easier as only the reference in the symbol table needs to be changed.
  The interpreter REPL might also have a command to overwrite the attribute which allows the function
  to be replaced.
- A format function to create textual representations of objects.  Optionally integrated with the I/O
  subsystem to additionally output the resulting string.  Uses format strings as Scheme's `format` or
  C++'s `std::format` and `std::print`.  The Scheme solution is an example to combine the two.  The
  formatting of arithmetic types can be defined per attribute attached to the type definition.  Using
  reflection a good default version can be created (as in Rust or in Haskell with the `Show` property).
- Combinators (from combinatorical logic) are defined using glyphs to combine functions to pipelines.
  For the most common functions operating on containers implementations are given.  The use of concise
  glyphs for these functions as in APL (especially TinyAPL), BQN, UIUA is the guiding principal.
  The equivalent of the ranges library in C++26 is available, at least.
- an anonymous function definition syntax (lambda functions) is available.  Parameters can have types
  but can also have no type (same as `auto` in C++).  Anonymous functions can be deconstructed and
  examined with the reflection functionality and even installed with a name in the global namespace.
  Anonymous functions can have closures but the lifetimes of imported objects needs to be respected.

The decisions about the details of the language are not made yet.  The details are discovered along the way
of performing experiments with multiple implementations of the various parts of the implementation.
Documentation of all the decision that have to be made, the experiments, and results have to be recorded.
The collection of these notes is also goal of the project.

It is absolutely necessary to achieve consistency of the results.  If operations are not associative it
might still be useful/desired to parallelize them.  But the work-splitting must be consistent so that
the combination of the intermediate results is consistent.


Implementation
==============

The implementation in the end should be self-hosted.  Ideally this means that a bootstrap version of the
interpreter is implemented in a commonly available language.  The bootstrap interpreter need not implement
the full version of the language, just enough to get handle a version of the language which allows to
run a non-optimized version of the language.  This version of the interpreter source code can elide all
kinds of optimization and target-specific code generation like GPU code generation.

The interpreter/compiler are meant to be used in quick edit-eval-check loops which might be completely
automated.  Automation requires that all output and all the useful internal information (such as the
decision made during optimization and code generation) are provided in a machine readable form as well.
One important output is an estimate for the amount of overhead code generated for each piece of code.
When a function is (partially) generic, the estimated must be given for each instantiation.  Using
this information the programmer or the agent can determine what to focus on in the optimization program.

It also means that the turn-around times must be fast: the interpreter/compiler must be highly parallelized
and start up and execute as quickly as possible, delaying/scheduing for parallel computation if necessary
work until it is needed.  The same applies to linking.  The object file format needs not be the native
platform format.  If it is, ensure that partial recompilation etc are possible.  For most compilations
except when generating the actual program the output will be a form of the internal representation of the
un-instatiated code of the function.

It must be possible to use code in the default form for the system.  For instance, at least for the first
time it will be necessary to link with the system's Vulkan library, likely the shared object version.
This requires a limited version of the dynamic linker to be available and possibly a simulated version of
the basic runtime (like C library etc).

The compiler must also have an language server protocol mode to be used in code editors and other tools.
As must information as possible must be exposed through the protocol, for understanding the code,
optimizing the code, debugging the code.

The compiler expects as argument one or more source files.  If any of them contain a comptime function
marked as build function by attribute or command line option, the instructions are taken from that
function.  Other all input files are compiled into one executable if any of the functions in the sources
is defined as the startup function.

The interpreter accepts zero or more source, if none is given this is the same as an empty file.  It reads
all the functions and locates the build and startup function.  If a build function is defined, information
about search paths and compiler flags are extracted.  If a startup function is defined and no command line
option to the contrary is provided, the interpreter starts executing the startup function after all necessary
parsing.  If no startup function is present or the interpreter is told to not execute it automatically,
a REPL loop is entered and the user can interact with the interpreter.

All files of the interpreter or compiled are stored in files or directories contained in the build
directory.  By default use a subdirectory `build` in the current directory.

The interpreter can compile functions as they are used.  The process should not delay execution but instead
just kick of the JIT compilation.  A latter invocation of the function might find the compiled function to
be available.  This is somewhat similar to Julia and just as that REPL there should be support to look at
the generated code, the machine code and the parse tree of the functions.


Runtime
=======

The runtime of the language is not meant to be based on existing runtime libraries.  Instead, the kernel
interfaces are to be used directly.  For embedded systems a minimal set of OS functions from an embedded
OS is imported.

The I/O system is asynchrous be default.  Ordering rules are to be defined (for threading, co-routines,
etc) but interfaces like straight terminal I/O or reading/writing files are not directly provided.  The
I/O functionality should be based on Linux systems around the `io_uring` system call.  The I/O
functionality of the Zig language from version 0.15 on can serve as an example.

Concurrency support should implemented using the system's kernel functionality.  On Linux system the
implementation should use the `clone3` system call and the futex functionality directly.

An execution content pool can be useful in several situations: when running gang concurrency but also
when running code for co-routines.  If executation contexts are not used, appropriately marked coroutines
might run lazily evaluated code opportunistically.  It must be possible to disable this because the
resources requirements to store intermediate results might be too large.  It would also be necessary to
define dependencies for the continuation of a co-routine to, for instance, clear a buffer to store the
last intermediate result.

The runtime should only pull in/create code for what is needed in the program.  This also means that only
the parts of the runtime that are needed should be iniatilized.


Design Choice and Experiments
=============================

- provide several examples for the syntax of the basic language constructs:
  - function definitions including type signatures
  - global variables with and without types, with or without initializer
  - conditionals
  - loops
    - different loop types
    - loop exits, perhaps non-local exits
  - function calls
  - function returns, including early one
  - special statements such as something like `match` to decompose arithmetic sum types and optional
  The primary goal is context-free syntax.  It must always be possible, with just the parser, to
  determine the end of the current function/variable/statement and so enable parallel parsing and
  compilation of functions and initialized variable definitions.  Keywords can be added to the language
  at a later time and prevented from being used as identifiers.
- instead of proliferating bad practice, potentially use × as multiplication operator, ÷ as division
  operator.  Provide a suggestion for modulus.
- Decide about semantic of integer division.  Have two operators like Python?  Explictly require that
  the behavior and output type is specified?  Potentially with two different prefixes/suffixe for the
  ÷ operator.  Or requiring that the ÷ operation is wrapped in an explicit cast, with integer cast
  and floating-point casts allowed.  Allow use of untyped casts which determine integer/floating-point
  division from the cast but the actual type from the types of the arguments.
- in strict mode (the default) arithmetic overflow/underflow must be reported or lead to termination.
- binary logic operations should use appropriate Unicode glyphs: ∧ (AND), ∨ (OR), ⊕ (XOR), ⊼ (NAND),
  ⊽ (NOR), ¬ (NOT).
- boolean operations should have the same range of operation as binary operations. A possible glyph for
  each can consist of the glyph for the binary operation followed by ₁.
- if the binary logic or the boolean operations operate on integers of different types, the semantic
  can be defined in various ways: mark as invalid, extend smaller with zeros, repeat smaller as many
  times as needed.  Possibly only accept the special case of one bit (i1 or bool).  Compare to other
  languages, run experiments.
- provide a way to select insecure mode for compilation-unit, function, or individual scopes, overwriting
  temporarily the previous setting.  Rust has something equivalent.
- there needs to be a syntax to attach attributes to variable/function definitions, individual statement,
  blocks, scopes.  Perhaps a wordy syntax is useful and implement a more compact syntax like Rust's using
  macros.
- whether or not operators have predence is not decided.  More experiments are needed, mostly to
  show the difference in the source code.  If arbitrary new operators can be defined or many operators
  are available in the language, precedence can get confusing (see Wolfram). No precedence with strict
  right-to-left processing (as in APL) can be one solution (or left-to-right).  Such an approach is
  confusing for anyone without APL knowledge since `4×3+2` is not evaluated as in most other languages.
  An alternative is to preserve precedence for the basic arithmetic operators and have all others the
  same.  This is still confusing for someone coming from C which has has boolean operators and more.
- operators and functions in general should be allowed to be inline or in functional form (prefix form of
  the function name, possible reverse notation as in Forth).  Experiments will show.
- operators should be possible with names from the Unicode code space.  Allow code points in the
  mathematical operator classes to be used.  Code points from letter or digit forms can be used in
  identifiers.
- to faciliate fast, parallel compilation and parsing in the interpreter the language must have a
  context-free grammar.  Keyword such as those in languages Rust, Go, etc are to be used.  Additional
  syntactic elements as commas, semicolons etc are to be used to disambiguated the syntax.
- at the same time, unnecessary tokens just for the purpose of symmetry etc are to be avoided.  E.g.,
  a code block for a statement or a function might not need the equivalent of an open brace or a `begin`
  keyword even though a closing token is present.
- how to implement the contract/condition/assertion system will require experimentation.  The syntax
  should allow simple syntax element as for simple operations (such as function calls and condition test)
  while at the same time allow sophisticated debug statements to be specified.  The main goal is to derive
  the tests from the same source as the human-understandable desription.  As in C++26 contracts, violations
  might be logged and/or cause termination or debugging access.
- how to represent units and derived units.  Example of derived unit: computation of speed on a radius in
  m/s given angle velocity and radius.  The angle volicity could just use 1/s of units and multiplied with
  radious yields the correct result.  But if the radius value is actually some unrelated value with unit
  m the result can still be nonsense.  What if the radius value has an additional attribute *radius* and the
  angle velicity a unit radiant/s.  The radiant value could include implicitly the factor pi or not.  The
  radiant attribute would only vanish if multiplied with a radius and the multiplication can still be
  performed correctly if a value with attribute diameter is given if an implict coversion
  diameter = 2×radius is defined.
- lazy evaluation might be useful but so is eager evaluation.  Both should be possible.  What is the default
  and where is to be determined.
- determine in which situations it might be necessary for performance reasons to allow the user to request
  explicit lifetime control of objects, if at all.  If it is useful language constructs such as `defer` are
  likely needed.
- determine address space/memory model for processes, especially with threads.  What should be shared at
  what time etc.  How to specify this in the source code?  There is no requirement to follow the POSIX model
  nor does the model have to be the same for all compiled programs.  Only consistency is required.
- design source code annotations to specify the floating-point handling, rounding, requested extra-precision
  etc
- experiment with way to integrate ratios.  There should be an explicit type (nominator and denomitor both
  using arbitrary precision integers) but there should also be an `untyped ratio` type (using the
  nomenclature of Odin) which exists at compile time and after parsing in the interpreter.  I.e., the
  interpreter/compiler should never preemptively perform the division to get the floating-point value but
  instead keep the `untyped ratio` value around (except when the result is an integer).  Basic arithmetic
  functions like square root and absolute value (functions in IEEE754) should be provided for rational.
  Others require the explicit casting to a floating point value.
- considering the language starts from scratch, there are no namespace issues, there are many different ways
  how identifiers used for variables, functions, types and the keywords of the language can be restricted,
  or not.  Requiring all types to start with a fixed prefix (maybe an Unicode glyph) or with uppercase
  characters can help compacting the syntax by avoiding some separator characters like comma or semicolon.
  Requiring uppercase means that it is not possible to use characters of non-alphabetic languages.  This
  still be OK since one could customarily prepend a `T`.  Use the Unicode character classes to determine
  glyphs that can be operators.
- when generating object files (or the equivalent thereof) in the compiler, there should not be a reason to
  use name mangling.  Just use a normalized, compact representation of the function name including the
  signature.
- the encoding used to represent types in object files must ensure that it covers all the aspects of the
  type definition.  Alignment, reordering, the number, order, and types of members of sum/product types etc
  all must be covered by the total name string.  The only requirement is that the constructed name is
  identical for equivalent definitions.  Even the name of members might be relevant since recompiling source
  with the names of two members with the same type reverse would lead to different compilation results.
  A hash sum covering the details other than the name is sufficient.
- There are many ways to implement a macro system.  Including the question how to deal with recusrive
  macros.  Experiment with concepts from Rust, Common Lisp, and whatever other languages has a good
  macro system.
- Introspection can potentially be implemented to a large extend with macros if the macro can get access
  to the tokens in the parse tree and dereference type and function names.  The goal is to match the
  functionality to C++26 and Rust and ideally allow arbitrary code inspection and generation of new
  code.  If the route 
- Translating functions accessing vectors/matrixes can be done in two ways:
  1. assuming dense representation using O(1) computed access with assumptions about caches
  2. using iterators and perhaps iterator arithmetic, allowing compacted representations
  Additionally information such as upper/lower triangle, diagonal matrix can be used for efficiency.
  All functions expecting matrix/vector arguments should also span/views of equivalent substructures.
- In languages like APL the glyphs for functions can have a binary and unary meaning, requiring the
  additional work to discover the actual meaning.  More recent array languages have fixed arity.
  Experiment with both approaches and document the respective advantages.
- there are many possible ways to distinguish macro invocations from function calls:
  - as in Rust, annotate the name
  - use a different syntax for the parameter list
  List different possibilities and provide experiments to decide.


Documentation
=============

Create Markdown files for all design considerations, experiments, results, decisions, and implementations
details and decisions.

When appropriate, reference the following languages in case one or more features of that language have
relevance in the decision making.  Describe the similarities and difference.  The following list of
languages might be added to in future:

- C and C++
- Zig
- Rust
- APL, TinyAPL, BQN, UIUA
- any modern LISP (SBCL, Clisp, Clojure, …), Scheme
- Prolog
- Forth
- Wolfram / Mathematica
- ML, CAML
- Python
- Swift
- Odin
- Julia

Provide actual code examples when explaining differences and similarities.  Elaborate when designing
language features to equivalencies of library-based implementations.  Decision making factors are
efficiency of implementation, readability of source code (including brevity).

The produced document is at the same time a documentation of the process to develop the language
as well as the definitive, normative reference manual for the language.  After every change the
reference section needs to be adjusted, if language changes are made.



How to Proceed
==============

1. if not explicitly tasked to do something, ask about the next aspect to be designed, provide suggestions
2. create a subdirectory for the documents and the generated source for the experiments and the results of
   the next feature to be designed and implemented
3. in the new subdir create first a document detailing the question to be answered when designing the
   solution
4. in the `newlang.md` file at the toplevel add a reference to the newly created design document at the
   end of the list at the end of the file.  Preserve the order.
5. create one or more experimental implementations.  the basis of the implementation is the result of the
   previous step, if it applies
6. perform experiments, judge the results, and ask for confirmation of the result by the user.  And no
   proposal is accepted or changes are requested, repeat the previous step
7. select a design, implement for the result using the previous step's result.  Document extensively the
   designs, experiments, and decision making process.
8. continue at step 1

The implementation of the result does not have to use the previous results.  Experiments can be standalone
code and this might also be advantageous since not that much code is involved.

At any point additional design choice can be documented.  Add them to the list in the section
Design Choice and Experiments.
