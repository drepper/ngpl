Creating a New Programming Language with Support for Automatic Code Generation
==============================================================================

Introduction
------------

This project documents the design and implementation of a new programming language built from the ground up. The language is conceived around a single guiding principle: **code should expose its intentions clearly enough to be understood, reviewed, and verified by humans, while remaining efficient enough for production use.**

### Goals

The language pursues several interrelated goals:

- **Static detection of problems.** Many classes of errors — type mismatches, unit inconsistencies, unsafe operations — are caught at compile time. The language encourages programmers to express contracts, assertions, and invariants that the compiler can check automatically.
- **Efficient execution.** When the programmer provides additional type information, annotations, and structural constraints, the compiler generates tight machine code. The same source can also run in an interpreted mode with boxed values for scripting and rapid development.
- **Human-understandable descriptions.** Contracts and assertions are not mere boilerplate; they serve as living documentation. The language generates readable summaries of program properties directly from the source.
- **Composability.** Functions are first-class objects. The language supports functional programming patterns, combinator-style pipelines, currying, and higher-order functions alongside imperative and concurrent styles.

### Language Features

The language itself is designed around a set of foundational choices:

- **Type system** supporting strict ( Hindley-Milner-like) and scripting modes, sum and product types with pattern matching, unit annotations for physical quantities, optional types, and rich numeric hierarchy including arbitrary-precision integers, floating-point types at various precisions, and rational numbers.
- **Expression syntax** optimized for clarity: no operator precedence confusion (experiments will determine the final approach), Unicode operators where expressive, and a consistent distinction between variable definitions and assignments.
- **Concurrency primitives** including gang execution, job-based parallelism, channels inspired by Occam and Go, and first-class coroutines — all with kernel-level support.
- **Memory management** without garbage collection: either explicit lifetime control (akin to Rust) or reference-counted boxed values, with stack allocation preferred when lifetimes are local.
- **Domain-specific constructs** for arithmetic on vectors, matrices, and tensors; sparse and specialized data structures; compile-time computation (`comptime`); and a hygienic macro system.

### The Interpreter

The interpreter serves as both a development environment and the bootstrap implementation of the language:

- A **REPL** supports interactive function calls, variable inspection, and incremental code loading.
- Functions are **JIT-compiled** as they are used, with fallback to interpretation for rapid iteration.
- The interpreter exposes internal state — parse trees, type information, generated intermediate representations — enabling tools that visualize and analyze code.
- It bootstraps the language: the full compiler is written in the language itself, with the interpreter serving as the initial compilation target.

### The Compiler

The compiler transforms source into efficient machine code:

- **Ahead-of-time (AOT) compilation** produces executables linked against a minimal runtime.
- **Ahead-of-time compilation to GPU targets** (e.g., Vulkan) for accelerated compute workloads.
- A **language server protocol (LSP)** mode powers editor integration, exposing types, contracts, and analysis results to IDEs and tools.
- Compilation is designed for **high parallelism and fast startup**, supporting rapid edit-eval-check cycles.

### The Runtime

The runtime is intentionally minimal and purpose-built:

- **Asynchronous I/O** built on `io_uring` (Linux) for high-throughput, low-latency operations.
- **Direct kernel interfaces** — `clone3`, futex, and similar syscalls — rather than abstraction layers.
- **Modular initialization**: only the runtime components actually used by a program are loaded and initialized.
- **Address spaces** as first-class language concepts, with configurable access costs and protection attributes.

### How It All Fits Together

The interpreter and compiler share a common front-end (scanner, parser, type checker) but diverge in their back-ends. The runtime provides the foundation for execution, I/O, concurrency, and memory management. All three components — language, tools, and runtime — are documented here as they are designed and implemented.

### Document Structure

This document is organized into chapters, each covering a distinct aspect of the language design and implementation:

1. **Lexical Analysis** — character encoding, Unicode handling, identifiers, literals, operators, comments, and macros
2. **Parsing and Syntax** — grammar design, context-free requirements, statement and expression syntax, scoping rules
3. **Type System** — base types, sum and product types, optional types, units, generics, type inference
4. **Expressions and Operators** — arithmetic, logical, boolean operations, casting, function calls, currying, combinators
5. **Functions and Control Flow** — definitions, purity, closures, lambdas, conditionals, loops, coroutines, lazy evaluation
6. **Concurrency and Address Spaces** — gangs, jobs, channels, execution contexts, address space model, memory sharing
7. **Data Structures** — vectors, matrices, tensors, maps, sets, strings, slices, views, sparse and specialized forms
8. **Modules and Build System** — module system, compilation units, build function, dependency management, SBOM generation
9. **Contracts, Assertions, and Documentation** — contract syntax, invariant checking, test integration, generated documentation
10. **Memory Management** — ownership, lifetimes, reference counting, stack allocation, explicit control
11. **Compile-Time Computation** — `comptime` semantics, metaprogramming, reflection, macro system, code generation
12. **The Interpreter** — architecture, REPL, JIT compilation, internal representations, debugging interfaces
13. **The Compiler** — front-end, optimization passes, code generation, GPU targets, LSP mode
14. **The Runtime** — asynchronous I/O, concurrency primitives, address spaces, memory allocator, startup sequence

Each chapter contains design questions, experiments with concrete examples, results, and final decisions. The reference sections within each chapter serve as the normative specification for that aspect of the language.


Chapter 3: Type System — Integer Types and Untyped Constants
------------------------------------------------------------

### Integer Types

The language provides fixed-width integer types with explicit signedness and bit count.  The naming convention uses a single letter (`i` for signed, `u` for unsigned) followed by the bit width:

| Type  | Width  | Range |
|-------|--------|-------|
| `i8`  | 8-bit  | -128 to 127 |
| `u8`  | 8-bit  | 0 to 255 |
| `i16` | 16-bit | -32768 to 32767 |
| `u16` | 16-bit | 0 to 65535 |
| `i32` | 32-bit | -2³¹ to 2³¹-1 |
| `u32` | 32-bit | 0 to 2³²-1 |
| `i64` | 64-bit | -2⁶³ to 2⁶³-1 |
| `u64`   | 64-bit | 0 to 2⁶⁴-1 |
| `usize` | platform | 0 to 2^N-1 (N = pointer width) |

`usize` is an unsigned integer type whose width matches the platform's pointer size, equivalent to `size_t` in C/C++.  On a 64-bit platform it is 64 bits wide.  It is the natural type for array indices, byte offsets, and object sizes.

Additionally, `int` denotes an arbitrary-precision integer with no fixed width.  This type can represent any integer value regardless of magnitude.

### Untyped Integer Constants

Integer literals in source code are of type **`untyped int`**.  An untyped integer is not yet committed to any specific integer type — it is a compile-time value that can be implicitly coerced to any integer type whose range can represent the value.

This concept is similar to Go's untyped constants and Odin's untyped integers.  The key properties are:

1. **Implicit coercion.**  An `untyped int` value can appear wherever a typed integer is expected.  The coercion is valid if the value fits in the target type's range.  For example, the literal `42` can be used as `u8`, `i32`, `u64`, or any other integer type.

2. **Compile-time range check.**  If a literal value does not fit in the target type, this is a compile-time error.  For example, `300` cannot be coerced to `u8` (max 255).

3. **Arithmetic on untyped integers.**  When two `untyped int` values are combined with an arithmetic operator, the result is also `untyped int` with arbitrary precision — no overflow occurs.  This allows compile-time constant expressions to compute exact results regardless of magnitude.

4. **Type inference with `var name := expr`.**  When a variable is defined with `:=` (no explicit type) and the initializer is an `untyped int`, the variable's type is `int` (arbitrary-precision).  To get a fixed-width type, use the explicit form: `var name : u32 = expr`.

5. **Array initialization.**  In `var name : u32[64] = 0`, the `0` is an `untyped int` that coerces to the array's element type `u32`.

### Examples

```
const K : u32 = [1116352408, 1899447441, ...];   /* array of u32, literals coerced */
var blk_off : usize = 0;                           /* usize variable for byte offsets */
var rem : usize = data_size % 64;                  /* remainder operator, result coerced to usize */
var i : u32 = 0;                                   /* u32 loop counter */
var hash := 0;                                     /* int (arbitrary-precision), inferred from untyped int */
var W : i32[64] = 0;                               /* array of 64 i32 elements, each initialized to 0 */
```

### Design Rationale

The `untyped int` approach avoids requiring suffixes on every integer literal (as in Rust's `42u32` or C++'s `42UL`) while still permitting precise type control through variable declarations.  It keeps the common case — writing plain numbers — clean and readable, while the type system ensures that values fit their containers at compile time.

This design also enables the arbitrary-precision `int` type to coexist naturally with fixed-width types: a literal `256` in a context expecting `u8` is a compile error, but the same literal in an untyped context simply represents the mathematical integer 256.

### Integer Remainder

The `%` operator computes the integer remainder with truncation toward zero, matching C, C++, and Rust semantics:

    a % b = a - trunc(a / b) * b

The result type follows the same rules as other arithmetic operators: `resolve_width` selects the wider operand's type.  For unsigned types, the result is always non-negative.


### Function Return Values

The `return` keyword is used for early returns from a function — exiting before the end of the function body.  For the final expression in a function body, the `return` keyword is optional: the last expression in the body, written without a trailing semicolon, is the function's return value.

This is consistent with expression-oriented languages like Rust, Haskell, and Zig where the last expression in a block is its value.  The rule is:

1. **Explicit return.**  `return expr;` exits the function immediately with the given value.  Required for early returns (e.g., inside an `if` branch before the end of the function body).

2. **Implicit return.**  The last statement in a function body, if it is a bare expression without a trailing semicolon, becomes the function's return value.  No `return` keyword is needed.

3. **Semicolon distinction.**  A trailing semicolon after the last expression discards its value — the function returns `none`.  Omitting the semicolon makes the expression the return value.  This mirrors Rust's semicolon semantics.

Eliding the `return` keyword only really comes into its own when functions are small and can be written
in possibly just a single function.  Requiring the use `return` in an inline-defined anonymous function
would require a significant amount of the total number of tokens for this construct.


#### Examples

```
fn add(a, b) -> int {
    a + b
}

fn abs(x) -> int {
    if (x < 0) { return -x; }
    x
}

fn greet(name) -> none {
    std.print("hello " + name);
}
```

In `add`, the expression `a + b` (no semicolon) is the implicit return value.  In `abs`, the early return uses `return`; the final `x` is an implicit return.  In `greet`, the semicolon after `std.print(...)` discards the result, so the function returns `none`.


### Built-in Test System

Unit testing is built into the language, similar to Rust's `#[test]` attribute.  Functions are annotated with `@test` to mark them as test functions.  The annotation accepts an optional list of function names that the test covers.

#### Annotation Syntax

```
@test
fn test_something() -> none { ... }

@test(sha256)
fn test_sha256_abc() -> none { ... }

@test(encrypt, decrypt)
fn test_round_trip() -> none { ... }
```

#### Execution Semantics

Test functions are always run unless explicitly skipped.  Their execution order depends on whether they reference specific functions:

1. **Standalone tests** (`@test` without references) run at startup, before the `@start` function.  If any standalone test fails, the program terminates immediately.

2. **Referenced tests** (`@test(func_name)`) run once, automatically, on the first call to any of the referenced functions.  This follows `pthread_once` semantics: the test executes exactly once regardless of how many times the referenced function is called.  If a test references multiple functions, it runs on whichever is called first.

3. **Test mode** (`--test` flag) runs all tests — both standalone and referenced — without executing the `@start` function.  The interpreter reports results and exits with status 0 (all passed) or 1 (any failed).

#### Assertion Functions

Two built-in assertion functions are available in all scopes:

- `assert(condition)` — fails if the condition is `false` or zero.  An optional second argument provides a custom error message: `assert(x > 0, "x must be positive")`.

- `assert_eq(expected, actual)` — fails if the two values differ.  The error message displays both values for easy comparison.  Large integers (such as cryptographic hashes) are displayed in hexadecimal.

#### Test Output

In normal mode, test results are printed to stderr as they run:
```
test test_sha256_empty ... ok
test test_sha256_abc ... ok
```

In `--test` mode, a summary follows:
```
running 3 tests
test test_sha256_empty ... ok
test test_sha256_abc ... ok
test test_sha256_448bit ... ok

test result: ok. 3 passed; 0 failed
```

#### Example: FIPS 180-4 SHA-256 Test Vectors

```
@test(sha256)
fn test_sha256_empty() -> none {
    var data := std.bytes("");
    var hash := sha256(data);
    assert_eq(hash, 0xe3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855);
}

@test(sha256)
fn test_sha256_abc() -> none {
    var data := std.bytes("abc");
    var hash := sha256(data);
    assert_eq(hash, 0xba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad);
}
```

#### Design Rationale

The test system draws from several languages:

| Feature | Rust | Zig | This language |
|---------|------|-----|---------------|
| Annotation | `#[test]` | `test` block | `@test` / `@test(func)` |
| Runs with program | No (`cargo test` only) | No | Yes (always, unless skipped) |
| Function-level binding | No | No | Yes (`@test(func)` triggers on first call) |
| Assertion | `assert!` macro | `std.testing.expect` | `assert` / `assert_eq` builtins |

The function-level binding via `@test(func)` is unique to this language.  It ensures that a function's tests run before the function is ever used in production, catching regressions at the earliest possible point.  The `pthread_once` execution model ensures no runtime overhead after the first call.

The `std.bytes(string)` function creates a `Bytes` object from a UTF-8 string literal, enabling test functions to construct known inputs for cryptographic and binary data operations.
