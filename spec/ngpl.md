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

4. **Type inference with `let name := expr`.**  When a binding is defined with `:=` (no explicit type) and the initializer is an `untyped int`, the binding's type is `int` (arbitrary-precision).  To get a fixed-width type, use the explicit form: `let name : u32 = expr`.

5. **Array initialization.**  In `let name : mut u32[64] = 0`, the `0` is an `untyped int` that coerces to the array's element type `u32`.

### Examples

```
let K : u32 = [1116352408, 1899447441, ...];       /* array of u32, literals coerced */
let blk_off : mut usize = 0;                       /* mutable usize binding for byte offsets */
let rem : mut usize = data_size % 64;              /* remainder operator, result coerced to usize */
let i : mut u32 = 0;                               /* mutable u32 loop counter */
let hash := 0;                                     /* int (arbitrary-precision), inferred from untyped int */
let W : mut i32[64] = 0;                           /* array of 64 i32 elements, each initialized to 0 */
```

### Design Rationale

The `untyped int` approach avoids requiring suffixes on every integer literal (as in Rust's `42u32` or C++'s `42UL`) while still permitting precise type control through variable declarations.  It keeps the common case — writing plain numbers — clean and readable, while the type system ensures that values fit their containers at compile time.

This design also enables the arbitrary-precision `int` type to coexist naturally with fixed-width types: a literal `256` in a context expecting `u8` is a compile error, but the same literal in an untyped context simply represents the mathematical integer 256.

### Fast Integer Types

For each fixed-width integer type, a corresponding **fast** variant exists that is at least as wide as the base type but may be wider if the platform can operate on the wider type more efficiently.  The naming convention appends `fast` to the base type name:

| Fast type | Minimum width | x86_64 width | Underlying type |
|-----------|---------------|--------------|-----------------|
| `u8fast`  | 8-bit  | 32-bit | `u32` |
| `i8fast`  | 8-bit  | 32-bit | `i32` |
| `u16fast` | 16-bit | 32-bit | `u32` |
| `i16fast` | 16-bit | 32-bit | `i32` |
| `u32fast` | 32-bit | 64-bit | `u64` |
| `i32fast` | 32-bit | 64-bit | `i64` |
| `u64fast` | 64-bit | 64-bit | `u64` |
| `i64fast` | 64-bit | 64-bit | `i64` |

The primary use case is **loop indices and local counters** where the exact width is unimportant but performance matters.  On some 64-bit platforms, 32-bit operations are fastest (due to shorter instruction encodings and implicit zero-extension); on others, native 64-bit operations are faster.  Fast types let the compiler choose the optimal width for the target.

#### Wrapping Behavior

Fast types wrap at the width of their underlying type, not the minimum width.  For example, `u8fast` on x86_64 wraps at 2³² (not 2⁸):

```
let x : mut u8fast = 255
x ← x + 1
/* x is 256, not 0 — because u8fast is 32-bit on this platform */
```

This means code using fast types must not rely on narrow wrapping behavior.  If wrap-at-8-bit semantics are needed, use `u8` explicitly.

#### Restriction: No Fast Types in Data Structures

Fast types **cannot** be used in data structure definitions that are visible outside function scope.  This prevents platform-dependent memory layouts from leaking across compilation boundaries:

- **Array element types**: `let arr : mut u8fast[64] = 0` is an error
- **Let definitions**: `let K : u32fast = [...]` is an error
- **Struct/product type members**: not allowed (when implemented)

Fast types **are** allowed for:

- Local scalar bindings: `let i : mut u32fast = 0`
- Loop indices: `foreach k : u32fast = 0…63:`
- Function parameters: `fn f x : u32fast → int:`

#### Design Rationale

This design mirrors C's `uint_fast8_t` family from `<stdint.h>` but with a cleaner naming convention and stricter usage rules.  The C standard allows fast types anywhere, which can lead to surprising behavior when data structures have different sizes on different platforms.  Restricting fast types to local computation prevents this class of portability bugs while preserving the performance benefit for the common case of loop indices.

| Feature | C (`<stdint.h>`) | Rust | Zig | NGPL |
|---------|-----------------|------|-----|---------------|
| Fast types | `uint_fast8_t` etc. | none | none | `u8fast` etc. |
| Data structure restriction | none | N/A | N/A | enforced |
| Width guarantee | at least N bits | N/A | N/A | at least N bits |
| Naming | verbose | N/A | N/A | `Nfast` suffix |


### The `byte` Type

The `byte` type is an 8-bit unsigned integer (semantically identical to `u8`) used specifically for raw data and I/O operations.  It occupies the range 0 to 255.

While `byte` and `u8` have the same representation and coercion rules, `byte` signals intent: the value represents raw data rather than a numeric quantity.  Arithmetic on `byte` values follows the same wrapping rules as `u8`.


### Integer Overflow Semantics

Integer overflow behavior depends on whether the type is **signed** or **unsigned**:

#### Unsigned Types: Modular Arithmetic

Unsigned types (`u8`, `u16`, `u32`, `u64`, `usize`, `byte`, and all unsigned fast variants) use **modular arithmetic**.  Operations that exceed the type's range silently wrap:

```
let x : mut u8 = 255
let y : mut u8 = 1
let z : mut = x + y          /* z is 0 (wrapped modulo 256) */

let a : mut u32 = 4294967295
let b : mut u32 = 1
let c : mut = a + b           /* c is 0 (wrapped modulo 2³²) */

let d : mut u8 = -1          /* d is 255 (modular representation) */
```

This matches C's unsigned semantics and Rust's `Wrapping<T>`.  Algorithms like SHA-256 depend on this behavior.

#### Signed Types: Overflow Aborts

Signed types (`i8`, `i16`, `i32`, `i64`, and all signed fast variants) **abort on overflow**.  Any arithmetic operation that produces a result outside the type's range raises an `OverflowError`:

```
let x : mut i8 = 127
let y : mut i8 = 1
let z : mut = x + y           /* ERROR: integer overflow */

let a : mut i32 = -2147483648
let b : mut = -a              /* ERROR: integer overflow (negation) */
```

This is the default strict mode behavior, as mandated by the language design: "in strict mode arithmetic overflow/underflow must be reported or lead to termination."

#### Untyped `int`: Arbitrary Precision

The untyped `int` type has arbitrary precision — overflow is impossible.  When a typed and untyped integer are combined, the result is `int` (arbitrary precision), so overflow cannot occur in mixed expressions.

#### Coercion Overflow

Assigning an untyped integer literal to a signed typed variable checks that the value fits:

```
let x : mut i8 = 128         /* ERROR: 128 does not fit in i8 (range -128..127) */
let y : mut u8 = 256         /* y is 0 (unsigned wraps) */
```

#### Bitwise Operations

Bitwise operations (`&`, `|`, `^`, `~`, `«`, `»`, `↺`, `↻`) always produce wrapped results regardless of signedness, since they operate on the bit representation and the result is always in range after masking.


### Floating-Point Types

The language provides IEEE 754 floating-point types at several precisions, plus an untyped `float` for general-purpose computation:

| Type    | Width  | Standard       | Significand | Exponent |
|---------|--------|----------------|-------------|----------|
| `f16`   | 16-bit | IEEE 754 half  | 11 bits     | 5 bits   |
| `bfloat` | 16-bit | Brain float    | 8 bits      | 8 bits   |
| `f32`   | 32-bit | IEEE 754 single | 24 bits    | 8 bits   |
| `f64`   | 64-bit | IEEE 754 double | 53 bits    | 11 bits  |
| `float` | 64-bit | (default)      | 53 bits     | 11 bits  |

`float` is the default floating-point type, equivalent to `f64` in precision.  It is the type inferred when a floating-point literal has no explicit width suffix.

`bfloat` (Brain Floating Point) uses the same exponent range as `f32` but truncates the significand to 8 bits, making it suitable for machine learning workloads where dynamic range matters more than precision.

#### Floating-Point Literals

Floating-point literals use decimal notation with a mandatory decimal point or exponent:

```
3.14                    // float (untyped, default precision)
1.0f32                  // f32 — explicit width suffix
2.5f64                  // f64
42f16                   // f16 — integer value with float suffix
1e3                     // float — exponent notation (= 1000.0)
1.5e-3                  // float — negative exponent (= 0.0015)
2.5e2                   // float — (= 250.0)
```

Hexadecimal floating-point literals use `0x` prefix with `p`/`P` exponent (base-2):

```
0x1.8p1                 // 1.5 × 2¹ = 3.0
0x1p0                   // 1.0
0x1p-1                  // 0.5
0x1.921fb6p1f32         // π as f32
```

A number literal is interpreted as floating-point when any of the following are true:
1. It contains a decimal point followed by digits (e.g., `3.14`)
2. It contains an exponent (`e`/`E` for decimal, `p`/`P` for hex)
3. It has a float type suffix (`f16`, `f32`, `f64`, `bfloat`)

#### Arithmetic on Floating-Point Values

All standard arithmetic operators (`+`, `-`, `*`, `/`, `%`) work on floating-point values.  When both operands are floats, the result uses the wider of the two types.  The width promotion order is: `f16`/`bfloat` < `f32` < `f64`/`float`.

```
let a : mut = 3.0 + 2.0      // 5.0 (float)
let b : mut = 1.5f32 * 2.0   // 3.0 (float — f32 promoted to float)
let c : mut = 10.0 / 4.0     // 2.5 (float)
let d : mut = 7.0 % 3.0      // 1.0 (float, uses fmod semantics)
let e : mut = -3.14           // -3.14 (negation)
```

Division by zero on floats produces an error (same as integer division by zero), not IEEE 754 infinity.

#### Mixed Integer-Float Arithmetic

When an integer and a float are combined in an arithmetic expression, the integer is promoted to the float type:

```
let a : mut = 2 + 3.0        // 5.0 — int promoted to float
let b : mut = 3 * 2.5f32     // 7.5 — int promoted to f32
let c : mut = 10.0 / 4       // 2.5 — int 4 promoted to float
```

This promotion is implicit and always safe (integers have exact float representations up to the significand width).

#### Float Comparisons

All comparison operators (`==`, `!=`, `<`, `>`, `<=`, `>=`) work on floats and mixed int-float pairs.  Integers are promoted to float before comparison:

```
static_assert(1.0 < 2.0)
static_assert(1.0 == 1)        // int promoted to float
static_assert(2 > 1.5)         // int promoted to float
```

#### Float Parameter Coercion

Function parameters with float type annotations accept both integer and float arguments.  Integers are converted to the target float type; floats are clamped to the target precision:

```
fn add x:f64, y:f64 -> f64:
  x + y
add(3, 4)               // both ints promoted to f64, result 7.0
add(3.14, 2)             // 3.14 is float→f64, 2 is int→f64
```

Passing a float to an integer parameter is a type error:

```
fn square x:i32 -> i32:
  x * x
@expect error "expected i32"
square(3.14)             // ERROR: float cannot coerce to integer
```

#### Precision Clamping

When a value is stored in a fixed-width float type, it is rounded to that type's precision using IEEE 754 round-to-nearest semantics.  The `bfloat` type truncates the lower 16 bits of the `f32` representation:

```
let x : mut f32 = 3.14      // stored as approximately 3.140000104904175
let y : mut f16 = 1.0       // exact in f16
```

#### Root Operators

Three unary prefix operators compute roots of floating-point values:

| Glyph | Name | Operation |
|-------|------|-----------|
| `√` (U+221A) | square root | x^(1/2) |
| `∛` (U+221B) | cube root | x^(1/3) |
| `∜` (U+221C) | fourth root | x^(1/4) |

Root operators are only allowed on floating-point values.  Applying them to integers is a type error:

```
let a : mut = √9.0           // 3.0
let b : mut = ∛27.0          // 3.0
let c : mut = ∜16.0          // 2.0
let d : mut = -√25.0         // -5.0 (negation binds looser than √)
let e : mut = √√256.0        // 4.0 (chained: fourth root)

let x : mut = 9
@expect error "floating-point"
let r : mut = √x             // ERROR: integer operand
```

When applied to a value with a unit, the root is also taken of the unit's dimensions.  Each dimension exponent must be divisible by the root degree, and the unit's conversion factor must be a perfect power:

```
let area ¤meter*meter : mut = 36.0
let side : mut = √area       // 6.0 m (√(m²) = m)

let vol ¤meter*meter*meter : mut = 125.0
let edge : mut = ∛vol        // 5.0 m (∛(m³) = m)

let d ¤meter : mut = 9.0
@expect error "exponent"
let r : mut = √d             // ERROR: √(m¹) has odd exponent
```

#### Power Operator

The binary operator `↑` (U+2191, UPWARDS ARROW) computes exponentiation.  It is right-associative and binds tighter than multiplication but looser than unary operators (except negation, which binds looser than `↑`):

```
let a : mut = 2 ↑ 10         // 1024 (integer)
let b : mut = 3 ↑ 4          // 81
let c : mut = 2.0 ↑ 0.5      // √2 ≈ 1.4142
let d : mut = 4.0 ↑ -0.5     // 1/√4 = 0.5
```

**Integer rules**: both operands must be integers.  The exponent must be non-negative (negative integer exponents are a type error since the result would be fractional).  Overflow is detected and reported:

```
let x : mut i8 = 2
@expect error "overflow"
let r : mut = x ↑ 8          // 256 overflows i8
```

**Float rules**: either or both operands may be float.  An integer operand is promoted to float.  Negative exponents are allowed:

```
let r : mut = 2.0 ↑ -1.0     // 0.5
```

**Precedence and associativity**:

- Right-associative: `2 ↑ 3 ↑ 2` = `2 ↑ (3 ↑ 2)` = `2 ↑ 9` = 512
- Binds tighter than `*`: `2 * 3 ↑ 2` = `2 * 9` = 18
- Unary minus binds looser: `-2 ↑ 2` = `-(2 ↑ 2)` = -4

**With units**: a unit-bearing base raised to an integer exponent scales the unit dimensions accordingly.  The exponent itself cannot carry a unit:

```
let d ¤meter : mut = 3.0
let area : mut = d ↑ 2       // 9.0 m^2
let vol : mut = d ↑ 3       // 27.0 m^3
let r : mut = d ↑ 0       // 1.0 (dimensionless — m^0)
```

#### Truthiness

Float values are truthy when nonzero and falsy when exactly `0.0`:

```
if 1.5:
  // executes — nonzero float is truthy
if 0.0:
  // does not execute — zero float is falsy
```


### Binary Logic Operations

Binary logic operations use Unicode glyphs and operate on logical truth values.  Unlike bitwise operations (which manipulate individual bits), these first reduce each operand to a boolean and then apply the logic function.  The result is always `bool`.

#### Operators

| Glyph | Name | Arity  | Definition |
|-------|------|--------|------------|
| `∧`   | AND  | binary | true when both operands are truthy |
| `∨`   | OR   | binary | true when at least one operand is truthy |
| `⊕`   | XOR  | binary | true when exactly one operand is truthy |
| `⊼`   | NAND | binary | true when not both operands are truthy |
| `⊽`   | NOR  | binary | true when neither operand is truthy |
| `¬`   | NOT  | unary  | true when the operand is falsy |

#### Operand Conversion

For `bool` operands the value is used directly.  For integer operands (`i8`, `u32`, `int`, etc.) a nonzero test is applied: zero maps to `false`, any nonzero value maps to `true`.  Floating-point operands are not allowed and produce a type error.

```
let a : mut i32 = 42
let b : mut i32 = 0
a ∧ b                       /* false — 42 is truthy, 0 is falsy */
a ∨ b                       /* true  — at least one is truthy */
¬b                           /* true  — 0 is falsy */
```

#### Precedence

The logic operators follow standard Boolean algebra precedence, all binding tighter than the short-circuit keywords `and`/`or` and looser than comparison operators:

| Tightest → Loosest | Operators |
|---------------------|-----------|
| comparison          | `==`, `!=`, `<`, `>`, `<=`, `>=` |
| logic AND/NAND      | `∧`, `⊼` |
| logic XOR           | `⊕` |
| logic OR/NOR        | `∨`, `⊽` |
| short-circuit AND   | `and` |
| short-circuit OR    | `or` |

This means `a == 0 ∧ b != 0` parses as `(a == 0) ∧ (b != 0)`, and `x ∧ y ∨ z` parses as `(x ∧ y) ∨ z`.

#### Element-wise on Arrays

Like arithmetic operators, the logic operators iterate element-wise over arrays and vectors:

```
let a : mut i32[3] = 0
a[0] ← 1; a[1] ← 0; a[2] ← 5
let b : mut i32[3] = 0
b[0] ← 3; b[1] ← 0; b[2] ← 0
let r : mut = a ∧ b              /* [true, false, false] */
```

#### Distinction from Other Operators

| Category | Operators | Semantics |
|----------|-----------|-----------|
| Bitwise  | `&`, `\|`, `^`, `~` | operate on individual bits, result is an integer of the same type |
| Logic    | `∧`, `∨`, `⊕`, `⊼`, `⊽`, `¬` | nonzero test then logic function, result is `bool` |
| Short-circuit | `and`, `or`, `not` | like logic but short-circuit evaluation, result is `bool` |


#### Explicit Wrapping with `@wrap`

The `@wrap(expr)` annotation enables modular arithmetic for all operations within its scope, even for signed types that would normally abort on overflow.  This is useful for cryptographic algorithms and other code that intentionally uses wrapping arithmetic on signed types:

```
let x : mut i8 = 127
let y : mut i8 = 1
let z : mut = @wrap(x + y)      /* z is -128 (wraps instead of aborting) */

let a : mut i32 = -2147483648
let b : mut = @wrap(-a)          /* b is -2147483648 (wraps instead of aborting) */
```

`@wrap` applies to the entire expression within the parentheses, including nested sub-expressions and function arguments.  Operations outside the `@wrap` scope retain their normal overflow behavior:

```
let x : mut i8 = 127
let y : mut i8 = 1
let safe : mut = @wrap(x - y)    /* wrapping subtraction */
let z : mut = x + y               /* ERROR: still aborts outside @wrap */
```

For unsigned types, `@wrap` is a no-op since they already use modular arithmetic, but it serves as documentation of intent:

```
/* SHA-256 compression round — u32 additions intentionally wrap. */
let t1 := @wrap(v[7] + s1 + ch + K[t] + W[t])
```

#### Design Rationale

| Feature | C | Rust | Zig | NGPL |
|---------|---|------|-----|---------------|
| Signed overflow | UB | panic (debug) / wrap (release) | UB / `@addWithOverflow` | abort |
| Unsigned overflow | wraps | wraps | wraps | wraps |
| Compile-time check | sometimes | yes | yes | yes |
| Arbitrary precision fallback | no | no | `comptime_int` | `int` type |

The split between unsigned (wraps) and signed (aborts) reflects a fundamental semantic difference: unsigned types represent bit patterns and modular counters, while signed types represent mathematical integers where overflow is a logic error.  This avoids the undefined behavior of C while being less surprising than Rust's debug/release split.


### Dynamic Arrays as Parameters

Function parameters can be annotated with dynamic array types using the `type[]` syntax:

```
fn process data : byte[] → int:
    ...
```

A dynamic array parameter carries its size implicitly.  The size is accessible via the `.sizeof` property:

```
fn count_bytes data : byte[] → usize:
    data.sizeof
```

#### Fixed-size vs. Dynamic Array Parameters

| Syntax | Meaning |
|--------|---------|
| `data : byte[64]` | Fixed-size array of 64 bytes — a single value |
| `data : byte[]` | Dynamic-size array — carries hidden size, queryable via `.sizeof` |

Fixed-size array parameters behave as a single value of known extent.  Dynamic array parameters behave like a fat pointer: the array data and its length travel together.

#### Array Size Compatibility

A dynamic array parameter (`type[]`) accepts any array of the correct element type, regardless of its size — both fixed-size and dynamic arrays can be passed:

```
fn sum(arr : i32[]) → i32:
    let total : mut = 0
    foreach i := 0…(arr.sizeof - 1):
        total ← total + arr[i]
    total

let fixed : mut i32[3] = [10, 20, 30]
sum(fixed)      // OK: fixed-size array accepted by dynamic param
```

A fixed-size array parameter (`type[N]`) accepts only arrays whose length is exactly `N` — the check is performed at runtime:

```
fn triple(arr : i32[3]) → i32:
    arr[0] + arr[1] + arr[2]

let dynamic : mut i32[] = [10, 20, 30]
triple(dynamic)     // OK: length matches exactly

let four : mut i32[] = [1, 2, 3, 4]
triple(four)        // error: expected i32[3] (length 3), got array of length 4
```

#### Coercion

When a `Bytes` object (from file I/O or `std.bytes()`) is passed to a `byte[]` parameter, it is automatically coerced to a byte array.  Each byte becomes an element of type `byte`.

#### Iteration

Dynamic arrays support iteration with `foreach`:

```
fn sum_bytes data : byte[] → int:
    let total : mut = 0
    foreach b := data:
        total ← total + b
    total
```

The loop iterates over each element of the array.  The loop variable is constant within the body (as with all `foreach` variables).

#### Design Rationale

| Feature | C | Rust | Zig | Go | NGPL |
|---------|---|------|-----|----|---------------|
| Array + size | separate pointer and length | slice `&[u8]` | `[]const u8` | `[]byte` | `byte[]` with `.sizeof` |
| Size access | manual tracking | `.len()` | `.len` | `len(s)` | `.sizeof` |
| Bounds checking | none | runtime panic | optional | runtime panic | planned |

The `.sizeof` property name is chosen to parallel the C/C++ `sizeof` operator while being a property of the array value rather than a compile-time operator.  It returns the number of elements, not the byte size (for `byte[]` these are identical, but for `u32[]` the element count and byte size differ).  The result carries unit `ptrdiff` for general arrays and unit `byte` for `u8[]` arrays.

The dynamic array type is the natural parameter type for functions that operate on variable-length data: hash functions, encoders, search routines.  The implicit size avoids the error-prone pattern of passing separate data and length parameters.


### Integer Remainder

The `%` operator computes the integer remainder with truncation toward zero, matching C, C++, and Rust semantics:

    a % b = a - trunc(a / b) * b

The result type follows the same rules as other arithmetic operators: `resolve_width` selects the wider operand's type.  For unsigned types, the result is always non-negative.


### Function Definition Syntax

Function definitions use the `fn` keyword followed by the function name, a parenthesized parameter list, an optional return type, and a block body.  An empty parameter list is written as `()`.  The ASCII form `->` is accepted as an alternative to `→`.

#### Grammar

```
fn name '(' [param1 [: type1] [, param2 [: type2] ...]] ')' [→ return_type] block
```

The function name is a single identifier.  Parameters are enclosed in parentheses and separated by commas.  Each parameter is an identifier optionally followed by `: type`.  The return type is introduced by `→` (or the ASCII equivalent `->`).  The block is either a layout block (`:`) or a brace block (`{`).

#### Examples

```
fn main() → ∅:                               /* no parameters */
    std.print("hello")

fn add(a : int, b : int) → int:              /* two typed parameters */
    a + b

fn identity(x) → int:                        /* untyped parameter */
    x

fn sha256(data : byte[]) → int?:             /* dynamic array parameter */
    ...
```

#### No-Parameter Functions

Functions with no parameters use an empty parameter list `()`:

```
fn main() → ∅:
    ...

fn test_something():
    ...
```

#### Disambiguation

Inside the parameter list, `:` always introduces a type annotation because the parameter list is explicitly delimited by `)`.  Outside the parameter list, `:` introduces a layout block and `{` introduces a brace block.  Optional (`T?`) and expected (`T?E`) postfixes are parsed after the base type identifier.

#### Design Rationale

The parenthesized parameter list makes the function signature unambiguously context-free — the parser always knows where parameters end, regardless of type annotations.  This is consistent with most contemporary languages.

| Feature | C/C++ | Rust | Haskell | Python | Zig | NGPL |
|---------|-------|------|---------|--------|-----|---------------|
| Parameter delimiters | `(...)` | `(...)` | none | `(...)` | `(...)` | `(...)` |
| Parameter separator | `,` | `,` | space | `,` | `,` | `,` |
| Return type | trailing or leading | `-> T` | `:: T` | `-> T` | `T` | `→ T` |
| Terminator | `{` | `{` | `=` | `:` | `{` | `:` or `{` |


### Function Purity

Functions are **pure by default**: they may only depend on their parameters and locally defined variables.  A pure function cannot read or write mutable global variables.  Accessing constants, calling other functions (pure or impure), and using locally defined variables are all permitted.

The `@impure` annotation lifts the restriction.  An impure function may read and write mutable global variables freely.

#### What is a mutable global?

A top-level binding introduced with `let mut` is a mutable global.  Bindings introduced with `let`, `fn`, or `enum` are immutable and visible to all functions regardless of purity.

#### Rules

1. A pure function **cannot read** a mutable global variable.
2. A pure function **cannot write** to any non-local variable (mutable global or otherwise).
3. A pure function **can** read constants and call any function (pure or impure).
4. An `@impure` function has no restrictions on global access.

#### Examples

```
let counter : mut = 0
let LIMIT := 100

fn pure_ok(x : int) → int:           /* pure — uses only parameter */
    x * 2

fn reads_const() → int:              /* pure — constants are not mutable globals */
    LIMIT

@impure
fn bump() → ∅:                       /* impure — reads and writes counter */
    counter ← counter + 1
```

Violating purity is a runtime error:

```
fn bad_read() → int:                  /* ERROR: pure function cannot read mutable global */
    counter

fn bad_write() → ∅:                   /* ERROR: pure function cannot assign to non-local */
    counter ← 1
```

#### Calling impure functions from pure functions

A pure function may call an impure function.  The impure callee is responsible for the side effect; the call itself does not make the caller impure.  This keeps the annotation burden low — only functions that directly access mutable state need `@impure`.

#### Comparison with other languages

| Language | Default | Opt-in impurity | Enforcement |
|----------|---------|-----------------|-------------|
| Haskell | pure | `IO` monad | type system |
| Rust | pure (by convention) | `unsafe` (different scope) | — |
| D | `pure` attribute | default is impure | compiler |
| Zig | — | — | no purity system |
| NGPL | pure | `@impure` annotation | runtime |

Haskell enforces purity through the type system — impure computations have a different type (`IO a`).  D inverts the default: functions are impure unless annotated `pure`.  NGPL follows Haskell's philosophy (pure by default) but uses a simpler annotation mechanism (`@impure`) rather than a monadic type.

#### Design Rationale

Purity by default encourages a functional style and makes functions easier to reason about, test, and parallelize.  The `@impure` annotation makes side effects visible at the definition site rather than requiring the reader to trace through the function body.  Runtime enforcement (rather than compile-time) is appropriate for the interpreter; the compiler will move this check to compile-time where possible.


### Unicode and ASCII Arrow Equivalences

The language uses Unicode arrows as the canonical forms for two syntactic roles:

| Unicode | ASCII | Usage |
|---------|-------|-------|
| `→` (U+2192) | `->` | return type annotation |
| `←` (U+2190) | `<-` | assignment |

Both forms are always accepted.  The lexer normalizes the ASCII forms to their Unicode equivalents, so `fn f x : i32 -> i32:` and `fn f x : i32 → i32:` are identical to the parser.  Similarly, `x <- 5` and `x ← 5` produce the same token.

The Unicode forms are preferred in source code for visual clarity and consistency with the other Unicode operators (`«`, `»`, `↺`, `↻`, `∧`, `∨`, `⊕`, `⍴`, `⧺`).  The ASCII forms exist to support environments where entering Unicode characters is inconvenient.


### Function Return Values

The `return` keyword is used for early returns from a function — exiting before the end of the function body.  For the final expression in a function body, the `return` keyword is optional: the last expression in the body, written without a trailing semicolon, is the function's return value.

This is consistent with expression-oriented languages like Rust, Haskell, and Zig where the last expression in a block is its value.  The rule is:

1. **Explicit return.**  `return expr;` exits the function immediately with the given value.  Required for early returns (e.g., inside an `if` branch before the end of the function body).

2. **Implicit return.**  The last statement in a function body, if it is a bare expression without a trailing semicolon, becomes the function's return value.  No `return` keyword is needed.

3. **Semicolon distinction.**  A trailing semicolon after the last expression discards its value — the function returns `∅`.  Omitting the semicolon makes the expression the return value.  This mirrors Rust's semicolon semantics.

Eliding the `return` keyword only really comes into its own when functions are small and can be written
in possibly just a single function.  Requiring the use `return` in an inline-defined anonymous function
would require a significant amount of the total number of tokens for this construct.


#### Examples

```
fn add a : int, b : int → int:
    a + b

fn abs x : int → int:
    if x < 0: return -x
    x

fn greet name → ∅:
    std.print("hello " + name);
```

In `add`, the expression `a + b` (no semicolon) is the implicit return value.  In `abs`, the early return uses `return`; the final `x` is an implicit return.  In `greet`, the semicolon after `std.print(...)` discards the result, so the function returns `∅`.

The same functions can equivalently be written with braces:

```
fn add a : int, b : int → int { a + b }
fn abs x : int → int { if x < 0 { return -x; } x }
```


### Bindings: `let` and `mut`

The `let` keyword introduces a binding.  By default, bindings are **immutable** — they cannot be reassigned after initialization.  Adding `mut` to the type makes the binding mutable.

```
let x := 42                  /* immutable, type inferred */
let y : i32 = 42             /* immutable, explicit type */
let z : mut = 0              /* mutable, type inferred */
let w : mut i32 = 0          /* mutable, explicit type */
```

#### An Unused `mut` Is a Warning

A binding marked `mut` that the function never modifies draws a warning, reported where the binding is written:

```
let unused : mut = 5

warning: 'unused' is declared mut but is never modified
```

The same applies to a parameter, reported at the parameter:

```
fn f(n : mut i32) → ∅:

warning: parameter 'n' is declared mut but is never modified
```

`mut` is a claim that the binding changes, and a reader who sees one plans around it — looking for where the value moves, or declining to reason about it as a constant.  A `mut` that never changes anything is either left over from code that used to change it, or a claim that was never true; both mislead in the same direction.

It is a warning rather than an error because the program is well-formed and may be mid-edit: a binding is often marked `mut` before the line that writes it is typed.

A statement-level `@expect` matches it, so a test can pin one binding without annotating the whole function:

```
@expect warning "'data' is declared mut but is never modified"
let data : mut = std.bytes("abc")
```

A marked statement handles its own diagnostics, so the warning is not also reported at the top level.  Other bindings in the same function are unaffected — marking one says nothing about the rest.

The warning is found before the program runs, unlike the warnings produced during evaluation, but `@expect` treats the two alike: what a diagnostic is about matters to the reader, and when it was noticed does not.

#### What Counts as Modifying

The check is deliberately generous, since a warning that fires where nothing is wrong is worse than one that stays quiet.  All of these count:

| Form | Example |
|------|---------|
| assignment | `x ← 1` |
| element or field assignment | `v[0] ← 1`, `p.x ← 1`, `m[0][1] ← 1` |
| a method that changes an array | `v.push(1)`, `v.pop()`, `v.insert(...)`, `v.remove(...)` |
| passing by reference | `f(&v)` — the callee may write through it |
| lending for writing | `foreach e := &mut v` |
| reshaping | `(2, 2) ⍴ v` — the result shares `v`'s storage |

Passing `&v` counts even when the parameter turns out to be a shared borrow, and reshaping counts even when the result is only read.  Following either through would mean resolving what happens next, and the cost of being wrong — a warning on correct code — is higher than the cost of staying quiet on a `mut` a stricter check would have caught.

The check is made where the function is defined, so it does not depend on the function being called.

#### What Immutability Covers

`let` protects what a binding names, not only the name.  An element or a field is part of the thing the binding holds, so writing to one is writing to the binding:

```
let v := [1, 2, 3]
v[0] ← 9

error: cannot assign to element of let variable 'v'
```

The whole chain of subscripts, slices, and fields is followed back to the binding it starts from, so reaching further in changes nothing:

```
let m := [[1, 2], [3, 4]]
m[0][1] ← 9        // same error, naming m
```

Reading is never restricted — only writes are.

The alternative, where `let` stops reassignment but leaves the contents open, makes the keyword nearly worthless for anything but scalars: an immutable binding to an array whose elements anyone may overwrite guarantees nothing a reader can rely on.  C's `const` applies to the pointer or the pointee depending on where it is written, which is the source of its reputation for confusion; here there is one rule and it covers everything the binding reaches.

This applies to every immutable binding, including function parameters and loop variables, which report their own kind:

```
foreach x := rows:
    x[0] ← 9        // error: cannot assign to element of foreach variable 'x'
```

#### Module-Level `let`

A module-level `let` defines a global constant visible throughout the compilation unit:

```
let PI := 3
let MAX_SIZE : u32 = 1024
```

Module-level immutable bindings are **not variables** — they need not occupy storage at runtime.  The compiler is free to substitute the value at every use site and eliminate the binding entirely.  This is a fundamental difference from C++, where `const` creates a variable with an immutable value that still has an address, a lifetime, and can be passed by reference.  In NGPL, taking the address of an immutable `let` binding is not permitted.

Module-level mutable bindings (`let name : mut type = expr`) are mutable globals.  They are accessible only from `@impure` functions (see [Function Purity](#function-purity)).

#### Function-Scope `let`

Inside a function body, `let` defines a local binding:

```
let pi := 3
let max_size : u32 = 1024
```

After initialization, any attempt to reassign or redefine an immutable binding is a compile-time (or runtime, in the interpreter) error:

```
let x := 42
x ← 99              /* ERROR: cannot assign to let binding 'x' */
let x : mut = 99    /* ERROR: cannot redefine let binding 'x' */
```

As with module-level constants, the compiler may eliminate function-scope `let` bindings that have values known at compile time.  When the initializer is not a compile-time constant, the binding behaves like a read-only local variable.

`foreach` loop variables are implicitly immutable — they cannot be reassigned with `←`.  Redefinition with `let` or `let ... : mut` is permitted but produces a warning (see [Constant Loop Variables](#constant-loop-variables)).

#### Comparison with Other Languages

| Feature | C/C++ | Rust | Zig | Go | NGPL |
|---------|-------|------|-----|----|---------------|
| Immutable binding | `const` | `let` (default) | `const` | no | `let` (default) |
| Mutable binding | (default) | `let mut` | `var` | (default) | `let : mut` |
| Immutable has address | yes | yes | no | N/A | no |
| Immutable eliminated | only with `constexpr` | only with `const` | yes | N/A | yes |

In C++, `const` creates a variable that happens to be immutable — it still has an address, participates in linkage, and can be passed by reference.  Only `constexpr` guarantees compile-time evaluation and potential elimination.  In Zig, `const` bindings are closer to NGPL: they are values, not locations, and the compiler eliminates them freely.  Rust's `const` items (module-level) are inlined at every use site like NGPL; Rust's `let` bindings (function-local) are immutable by default but always have an address.

Like Rust, NGPL defaults to immutability — `let` creates an immutable binding, and `mut` must be explicitly requested in the type.  This encourages a functional style where most bindings are never reassigned, and makes mutable state visible at the definition site.


### The Discard Target (`_`)

`_` is not a variable.  It is a place to put a value that is not wanted, and it names no storage:

```
_ ← compute_and_log()
```

It follows from that single fact that `_` never has to be declared, that anything at all may be assigned to it, and that it can never be read back.

#### No Declaration

There is nothing to declare.  `_` may be assigned to at any point, repeatedly, without a preceding `let`:

```
_ ← 1
_ ← 2
```

Nor is there a binding to redefine, so a second assignment is not a redefinition and raises none of the diagnostics that reassigning a `let` variable would.

#### Any Type

An assignment to a variable checks that the value fits the variable's type.  `_` has no type, because it has no storage, so no such check applies:

```
_ ← 42
_ ← "a string"
_ ← [1, 2, 3]
_ ← Point { x: 1, y: 2 }
_ ← ∅
```

The `let` form works too, and likewise imposes nothing:

```
let _ := read_config()
```

#### Reading Is an Error

```
_ ← 5
let n : mut = _

error: '_' discards the value assigned to it and cannot be read
```

This is what makes `_` worth having rather than a convention.  A name that can be written and read is a variable, and a variable called `_` is a variable with an uninformative name — the reader of `total ← _ + 1` has to search backwards to find out what `_` held.  Because reading is rejected, `_` in the source always means the same thing wherever it appears: a value being thrown away.  Nothing has to be traced.

The rule applies to every read, not only to a read after an assignment: as an operand, as an argument, as a condition, and to `_ ← _`, which is rejected for its right-hand side.

#### Other Binding Positions

`_` may stand wherever a name is bound, and means the same thing: the value is not wanted.  A loop that only needs to run a certain number of times, or that wants one of two loop variables:

```
foreach _ := 1…4:
    tick()

foreach i, _ := enumerate(values):
    std.print(i)
```

And a parameter a function does not use, which documents the fact in the signature rather than leaving a reader to check the body:

```
fn second(_ : int, keep : int) → int:
    keep
```

In each case the value is still produced — the loop still iterates, the argument is still evaluated and passed — and reading `_` inside the body remains an error.

#### Relation to Expression Statements

A bare expression statement already discards its value:

```
compute_and_log()
_ ← compute_and_log()
```

The two do the same thing, and the first is shorter.  The second says that discarding was intended.  Which to prefer is a matter of what the call looks like: for a function called only for its effect the bare form reads better, while for one that plainly returns something worth having, `_ ←` records that the result was considered and rejected rather than forgotten.

#### Comparison with Other Languages

| Feature | Go | Rust | Python | Zig | NGPL |
|---------|-----|------|--------|-----|---------------|
| Discard name | `_` | `_` | `_` (by convention) | `_` | `_` |
| Needs declaring | no | no | yes, it is a variable | no | no |
| Reading it | compile error | compile error | allowed | compile error | error |
| In loop bindings | yes | yes | by convention | yes | yes |
| As a parameter | yes | yes | by convention | yes | yes |
| Unused value must be discarded | yes, for variables | warning only | no | yes, error | no |

Go, Rust, and Zig all reject reading `_`, and this follows them.  Python is the outlier: there `_` is an ordinary variable that convention alone marks as unwanted, so `print(_)` is perfectly legal and the reader gains nothing from the name.

Zig goes further and makes discarding *mandatory* — an unused value is a compile error, and `_ = x;` is how a program says it meant it.  That is a defensible position and is not taken here: a bare expression statement remains a complete statement, and `_ ←` is available for when the intent is worth stating rather than required in order to compile.


### Optional Types (`T?`)

A function that may fail to produce a value declares an **optional return type** by appending `?` to the type name.  The optional type `T?` can hold either a value of type `T` (wrapped in `some`) or `∅` (absence of a value).

#### Declaration

```
fn get_padded_byte data : byte[], off ¤byte : usize, total_size ¤byte : usize → u8?:
    if off >= total_size: return ∅
    if off < data.sizeof: return data[off]
    ...
    0
```

A function with return type `u8?` auto-wraps non-`∅` return values in `some`.  Returning `∅` explicitly signals absence.  The caller receives either `some(value)` or `∅`.

#### The `?` Postfix Operator

The `?` operator unwraps an optional value or **propagates** `∅` to the enclosing function:

```
fn get_padded_word data : byte[], off : usize, total_size : usize → u32?:
    let b0 : mut u32 = get_padded_byte(data, off, total_size)?
    ...
```

Semantics of `expr?`:

1. If `expr` evaluates to `some(v)`, the `?` expression evaluates to `v`.
2. If `expr` evaluates to `∅`, the enclosing function immediately returns `∅`.
3. If the enclosing function does not have an optional or expected return type (`T?` or `T?E`), using `?` is a **compile error**.

This matches Rust's `?` operator.  The compile-time restriction ensures that `∅` propagation is always visible in the function signature — a function that cannot fail cannot silently swallow failures from callees.

#### The `??` Nil-Coalescing Operator

The `??` operator provides a default value when an optional is `∅`:

```
let b0 : mut u32 = get_padded_byte(data, off, total_size) ?? 0
```

Semantics of `expr ?? default`:

1. If `expr` evaluates to `some(v)`, the expression evaluates to `v`.
2. If `expr` evaluates to `∅`, the expression evaluates to `default`.
3. The right-hand side is evaluated lazily — only when the left is `∅`.

Unlike `?` which propagates `∅`, `??` recovers from it.  This is the right choice when absence has a known substitute value rather than being an error.

#### Type Widening on Assignment

When the unwrapped value has a narrower unsigned type than the target variable, implicit widening is permitted.  For example, `get_padded_byte` returns `u8?`; after `??` or `?` produces a `u8` value, assigning it to a `u32` variable widens it.  This is safe because every `u8` value is representable as `u32`.


### Naming a Present Optional (`∃`)

`∃(v)` is an optional that holds `v`, the counterpart of `∅` for absence.  It is Rust's `Some(v)` under a shorter spelling:

```
∃(42)                     // an optional holding 42
∅                       // an optional holding nothing
```

`some(v)` is the same constructor written as a keyword and remains accepted; `∃(v)` is the form to use, and the form an optional is shown as when a value is displayed rather than printed — `std.print` unwraps, as it does for every optional.

#### An Optional Is Not the Value It Holds

Comparing an optional with a plain value is an error:

```
v.get(0) == 1

error: ==: cannot compare an optional with a plain value; write ∃(v) to
compare against a present value, ∅ against an absent one, or ?? to
supply a default
```

This is what `∃` is for.  An equality that quietly looked through the optional would make

```
assert_eq(it.next(), 97)
```

read as a test of the element, when it is really a test of the element *and* of there being an element at all — two claims wearing the disguise of one.  The distinction matters most exactly where it is least visible: a test that passes because the iterator produced 97 and a test that would also have passed had it produced nothing are not the same test.  Written out, the intent is unambiguous:

```
assert_eq(it.next(), ∃(97))   // there was a value, and it was 97
assert_eq(it.next(), ∅)       // there was none
assert_eq(it.next() ?? 0, 97)  // 97, or nothing at all
```

Two optionals are compared by shape first and contents second, so nesting survives:

```
∃(∅) == ∅                 // false — one holds something, the other nothing
∃(∃(1)) == ∃(∃(1))       // true
```

Arithmetic and the other operators still unwrap implicitly, as [Implicit Unwrapping](#implicit-unwrapping) describes.  Only equality is strict, because only equality can silently answer a different question than the one asked.


### The `match` Statement

`match` dispatches on which shape a value has, binding what it holds:

```
match it.next():
    ∃(x):
        use(x)
    ∅:
        done()
```

Patterns are `∃(name)` for a present optional or a successful result, which binds the value to `name`; `∄(name)` for a failed result, which binds the error; `∅` for an absent optional; and `_` for anything not already matched.  Arms may be written in either order, and a single-statement arm may sit on the same line as its colon:

```
match v.get(i):
    ∃(x): total ← total + x
    ∅: break_out ← true
```

The name is bound only within its arm and cannot be assigned to: it names the value that was matched, and writing to it would say nothing about that value.

A falsy value is still a present one, so `∃(x)` takes an element of `0` — the arm chosen depends on whether there was a value, not on what it was.

#### Matching a Result

The same statement handles a result, with `∄(name)` binding the error:

```
match 10 / b:
    ∃(v):
        use(v)
    ∄(e):
        report(e)
```

`∃` covers both a present optional and a successful result because in each the question *was there a value* is answered yes, and the arm wants the value either way.  The two negative answers are distinct, and that is why they have separate patterns:

| Pattern | Answers "was there a value" | Says why not |
|---------|----------------------------|--------------|
| `∃(v)` | yes | — |
| `∅` | no | no |
| `∄(e)` | no | yes |

Neither stands in for the other.  A `match` on a result that handles only `∅` has not handled failure, and reports as much rather than falling through:

```
match 10 / 0:
    ∃(v): use(v)
    ∅: nothing()

error: match has no arm for a failed result; add the missing pattern or a _ arm
```

The glyphs are meant to read as what they say: `∃` there is a value, `∅` the set is empty, `∄` there is no value — and, since `∄` takes an argument, here is what stopped there being one.

#### Constructing a Failure (`∄`)

`∄(e)` is also an expression: a failed result carrying `e`.  It is how a function reports an error of its own rather than propagating one:

```
fn checked(n : int) → int!:
    if n < 0:
        return ∄(std.errors.invalid_argument)
    n * 2
```

Before this there was no way to write an error at all — expected values arose only from division, `catch`, and `?` propagation, so a function could pass a failure along but never originate one.  A function whose return type is expected auto-wraps an ordinary value in success, so only the failing path needs saying.

#### Coverage

A `match` given a value no arm accepts is an error rather than a silent no-op:

```
match v.get(0):
    ∃(x):
        std.print(x)

error: match has no arm for ∅; add the missing pattern or a _ arm
```

An optional has exactly two shapes and a result has two, so covering one means writing both arms or using `_`.

The check happens where the `match` is written, not where it runs.  A gap is a property of the code, so a missing arm that only an unlucky input would reach is reported all the same:

```
fn never_called() → ∅:
    let v : mut = [1]
    match v.get(0):
        ∃(x):
            std.print(x)

Error: in never_called: match has no arm for ∅; add the missing pattern
or a _ arm
```

#### Patterns That Cannot Match

A pattern belonging to a different type is reported as itself rather than as a missing arm, since naming the mistake is more use than naming its consequence:

```
match 10 / b:
    ∃(v): use(v)
    ∅: nothing()

error: ∅ cannot match a result, whose failure is ∄(e)
```

Two further mistakes need no knowledge of the subject at all, and are always reported: a repeated pattern, and an arm written after `_`.  Both are arms that can never run.

#### What Can Be Checked

Exhaustiveness needs the subject's type.  It is known for:

* a call to a function with a declared return type;
* division and remainder, which produce a result;
* `∃(...)`, `∅`, and `∄(...)` written out;
* the standard library's optional-returning methods — `next`, `get`, `pop` — unless a struct in scope defines a method of that name, in which case nothing is assumed.

Where it is not known — most often a `match` on a variable, whose type the interpreter does not track through assignment — no static claim is made and the gap is found when the `match` runs, as before.  This is the weaker half of the check and will shrink as type inference grows; nothing is reported wrongly in the meantime, since an undetermined type produces no diagnostic rather than a guess.

#### Choosing Between `match`, `??`, and `while`

Three constructs handle an optional, and they are not interchangeable:

| Construct | Use when |
|-----------|----------|
| `??` | a default will do, and the two cases need no separate code |
| `match` | both cases need their own code |
| `while name := …` | the value arrives repeatedly and absence ends the loop |

`match` is the general one and the most verbose; reaching for it where `??` suffices spends three lines to say what one says.

#### Comparison with Other Languages

| Language | Value present | Absent | Failed | Exhaustiveness |
|----------|--------------|--------|--------|----------------|
| Rust | `Some(x)` / `Ok(x)` | `None` | `Err(e)` | compile time |
| Swift | `.some(x)` / `.success(x)` | `nil` | `.failure(e)` | compile time |
| Zig | `\|x\|` on `if`/`while` | `else` | `else \|e\|` | n/a (not a match) |
| Scala | `Some(x)` / `Success(x)` | `None` | `Failure(e)` | compile time (warning) |
| NGPL | `∃(x)` | `∅` | `∄(e)` | compile time where the type is known |

The shape is Rust's, and the glyphs read as the mathematical statements they are.  Where Rust needs four constructors across two types — `Some`/`None` and `Ok`/`Err` — the same three patterns serve both here, because `∃` asks only whether a value arrived and does not care which type carried it.  That is a smaller vocabulary for the same coverage, at the cost of not distinguishing an optional from a result in the pattern itself.  Where this falls short of Rust and Scala is the reach of exhaustiveness rather than its existence: theirs follows from a type known for every expression, while here it covers the subjects whose type can be worked out and leaves the rest to a runtime check.  `match` is deliberately more general than optionals need: sum types will use the same statement, which is why the patterns are a list of shapes rather than a special form for `∃` and `∅`.


### Optionals in a Boolean Context

An optional may be used directly wherever a condition is expected.  It is true when it holds a value and false when it is `∅`:

```
let e : mut = it.next()
while e:
    use(e)
    e ← it.next()

if std.env.get("VERBOSE"):
    enable_logging()
```

Writing `e != ∅` means the same thing and remains correct; the direct form is shorter and is the one to prefer.

#### Presence, Not Truth

The test asks whether the optional *holds* a value, not whether that value is itself truthy.  This is C++'s `std::optional` and its `operator bool()`, which reports engagement: `std::optional<int> o = 0;` is true, because a zero is a value that is there.

The distinction matters exactly where it is easiest to get wrong:

```
let v : mut = [0, 0, 0]
let it : mut = v.iterate()
let e : mut = it.next()
while e:
    // runs three times, not zero
```

An element of `0`, `""`, or `false` is a value.  Only the absence of one ends the loop.  Under the other rule — testing the contained value — every loop over numbers would stop at the first zero, and the bug would appear only for the inputs that happen to contain one.

This extends to `∅` itself.  An optional holding `∅` is present:

```
let v : mut = [∅, 1]
```

iterates twice rather than none.  An operation that produces an optional marks it present, which is what separates "there was a value, and it was `∅`" from "there was no value".

#### A Bare Value Keeps Its Own Truthiness

Only an optional tests presence.  A value that is not one is still judged on its own terms, which is what the logic operators need:

```
if 0:            // false
if "":           // false
if v.get(0):     // true, even when the element is 0
```

The two rules coexist because they answer different questions.  `if 0` asks whether a number is nonzero; `if v.get(0)` asks whether there was an element to look at.  Collapsing them would force every caller of a fallible operation to spell out the comparison again.

#### Comparison with Other Languages

| Language | Optional in a condition | Tests |
|----------|------------------------|-------|
| C++ | `if (opt)` | engagement |
| Rust | `if opt.is_some()` | engagement, but explicit |
| Swift | `if let x = opt` | engagement, and binds |
| Zig | `if (opt) \|x\|` | engagement, and binds |
| Python | `if x is not None` | identity, explicit |
| NGPL | `if opt` | engagement |

C++ is the closest, and the one this follows.  Rust deliberately requires `is_some()` or a `match`, on the grounds that an implicit conversion hides a decision; that is a defensible position, but the cost lands on every loop over an iterator, which is the most common place an optional appears.  Swift and Zig bind the value in the same breath, which is more convenient still and needs syntax this language has not yet decided on.


### Expected Types (`T?E`) and Result Handling

An **expected type** `T?E` represents a computation that either succeeds with a value of type `T` or fails with an error of type `E`.  This is the language's counterpart to `Result<T,E>` in Rust and `std::expected<T,E>` in C++26.

#### Syntax

The `?` postfix on a type introduces an optional when no error type follows, and an expected when an error type is named:

| Syntax | Meaning |
|--------|---------|
| `T?` | optional — success (`∃(v)`) or absence (`∅`) |
| `T?E` | expected — success (`ok(v)`) or error (`err(e)` where `e` is of type `E`) |
| `T!` | abbreviation for `T?std.errors` |

```
fn safe_div a : int, b : int → int?std.errors:
    (a / b)?
```

Since `std.errors` is the most common error type, the abbreviation `T!` is provided:

```
fn safe_div a : int, b : int → int!:
    (a / b)?
```

`int!` is exactly equivalent to `int?std.errors` — both in parameter types and return types.  Since `std.errors` is what almost every fallible operation in the standard library reports, `T!` is the form to write; the long form is for the rare case of naming it alongside another error type, where the symmetry helps.  The rest of this document and the test suite use `T!`.

#### Constructors

An expected value is either `ok(value)` or `err(error)`:

- **`ok(v)`**: holds a success value.  Functions with an expected return type auto-wrap non-error return values in `ok`, just as optional-returning functions auto-wrap in `some`.
- **`err(e)`**: holds an error value of the declared error type `E`.

#### Division Returns Expected Values

Integer division and remainder (`/`, `%`) return an expected value with error type `std.errors` rather than raising a runtime exception:

```
let x : mut = 10 / 3           /* ok(3) — successful division */
let y : mut = 10 / 0           /* err(std.errors.division_by_zero) */
```

This means division by zero is a **recoverable error** rather than an immediate program abort.  The caller chooses the error-handling strategy:

```
/* Recovery with ?? */
let result : mut = (10 / 0) ?? -1         /* result is -1 */

/* Propagation with ? (requires T?E or T? return type) */
fn compute x : int → int!:
    let q : mut = (x / 2)?                /* propagates error if x/2 fails */
    q + 10
```

#### The `?` Operator on Expected Values

The `?` postfix operator works on both optional and expected values:

| Input | Behavior |
|-------|----------|
| `some(v)` | evaluates to `v` |
| `∅` | returns `∅` from enclosing function |
| `ok(v)` | evaluates to `v` |
| `err(e)` | returns `err(e)` from enclosing function (if return type is `T?E`) or `∅` (if `T?`) |

#### What `?` Requires of Its Function

`?` returns from the function it is written in, so that function has to be able to say that it failed.  Two rules follow, both checked when the function is defined rather than when the `?` runs.

**The return type must be optional or expected.**  A function returning a plain type has no way to report the failure it would be propagating:

```
fn broken(x : int) → int:
    let q : mut = (x / 2)?

error: in broken: ? requires the enclosing function to return an
optional or an expected type, but it returns 'int'
```

**An expected return must promise the error type being propagated.**  The caller reads the error as the declared type, so propagating a different one would hand it something it cannot interpret:

```
enum MyErr:
    bad

fn broken(x : int) → int?MyErr:
    let q : mut = (x / 0)?        // division fails with std.errors

error: in broken: ? propagates an error of type 'std.errors', but the
function returns errors of type 'MyErr'
```

An optional return (`T?`) needs no match: the error is converted to `∅` and the detail discarded, so any error type is absorbed.  An expected return (`T?E`) preserves the error, which is why it has to agree.

The error type is determined from the expression `?` is applied to — division and remainder fail with `std.errors`, and a call fails with whatever its own return type declares.  Where it cannot be determined without running the program, the check is made when the error is actually propagated instead.

A lambda is its own function for this purpose.  A `?` inside one returns from the lambda, so it is checked against the lambda's return type and not the enclosing function's:

```
fn caller() → ∅:                                  // plain, and that is fine
    let f : mut = λa : int, b : int → int!: (a / b)?
    std.print(f(10, 0) ?? ⁻1)
```

#### The `??` Operator on Expected Values

The `??` operator works on both optional and expected values.  For an expected error, the right-hand side provides the fallback:

```
let safe : mut = (x / y) ?? 0            /* 0 on division by zero */
let padded : mut = get_padded_byte(data, pos, total_size) ?? 0  /* 0 on absent byte */
```

| Input | Behavior |
|-------|----------|
| `some(v)` or `ok(v)` | evaluates to `v` |
| `∅` or `err(e)` | evaluates to the right-hand side |

#### Implicit Unwrapping

When an expected value holding `ok(v)` is used in an operation that expects a plain value (arithmetic, comparison, etc.), it is automatically unwrapped to `v`.  An expected value holding `err(e)` raises a runtime error at the point of use:

```
let x : mut = 10 / 3      /* x is ok(3) */
let y : mut = x + 1        /* x auto-unwraps to 3, y is 4 */

let z : mut = 10 / 0       /* z is err(std.errors.division_by_zero) */
let w : mut = z + 1        /* runtime error: unwrap of expected error */
```

This ensures that errors cannot be silently ignored — they must be handled (with `?` or `??`) or they surface at the next use site.

#### Example: Combining `?` and `??`

A function that returns `∅` for absent data, a caller that substitutes a default, and an outer function that propagates structural failure:

```
fn get_padded_byte ... → u8?:
    if pos >= total_size: return ∅
    ...
    ∅                                         /* zero-padding zone */

fn get_padded_word ... → u32?:
    if off >= total_size: return ∅             /* fully out of range */
    let b0 : mut u32 = get_padded_byte(...) ?? 0     /* absent bytes → 0 */
    let b1 : mut u32 = get_padded_byte(...) ?? 0
    let b2 : mut u32 = get_padded_byte(...) ?? 0
    let b3 : mut u32 = get_padded_byte(...) ?? 0
    (b0 « 24) | (b1 « 16) | (b2 « 8) | b3

fn sha256 data → int?:
    ...
    W[i] ← get_padded_word(...)?                   /* propagates ∅ */
    ...
    hash
```

Expected values and optionals compose naturally: a function returning `T?` can use `?` to propagate errors from callees returning `T?E` — the error is converted to `∅`.  A function returning `T?E` can propagate both expected-errors and optional-nones.

#### Design Rationale

| Feature | Rust | C++26 | Zig | Swift | NGPL |
|---------|------|-------|-----|-------|---------------|
| Optional type | `Option<T>` | `std::optional<T>` | `?T` | `T?` | `T?` |
| Result type | `Result<T,E>` | `std::expected<T,E>` | `!T` (error union) | — | `T?E` |
| Propagation | `?` operator | — | `try` / `catch` | — | `?` operator |
| Default value | `.unwrap_or(v)` | `.value_or(v)` | `orelse` | `??` | `??` operator |
| Compile-time check | Yes | Yes | Yes | — | Yes (must return `T?` or `T?E`) |
| Auto-wrapping | No (explicit `Some`/`Ok`) | No | No | No | Yes (auto `some`/`ok`) |
| Division error | panic | UB | — | — | `err(std.errors.division_by_zero)` |

The unified `?` syntax for both optional and expected types is intentional: both represent computations that may not produce a value, differing only in whether the failure carries a reason.  The postfix `T?` / `T?E` notation follows Swift's convention for optionals while extending it to expected types — the error type `E` appears naturally after `?`, keeping the syntax compact and context-free.

Division returning an expected value rather than panicking reflects the language's philosophy that errors should be **data**, not **exceptions**.  The caller decides the policy: propagate with `?`, recover with `??`, or let implicit unwrapping catch the error at the next use site.  This is analogous to Rust's approach where division on types implementing `checked_div` returns `Option<T>`, but here the error carries a typed reason (`std.errors.division_by_zero`) via the expected type.


### Function Parameter Types

Function parameters can be annotated with a type using the `name : type` syntax.  When a type annotation is present, the interpreter enforces type compatibility at each call site: arguments are coerced to the declared type, and a type mismatch is a runtime error.  Parameters without type annotations accept any value.

#### Valid Parameter Types

Only built-in types are currently accepted as parameter types:

| Category | Types |
|----------|-------|
| Signed integers | `i8`, `i16`, `i32`, `i64` |
| Unsigned integers | `u8`, `u16`, `u32`, `u64`, `usize` |
| Arbitrary-precision | `int` |
| Other | `bool`, `∅` |
| Optional | `?` postfix on any of the above (e.g., `u32?`, `bool?`) |
| Expected | `?E` postfix where `E` is an error type (e.g., `u32?std.errors`) |
| Expected (short) | `!` postfix, abbreviation for `?std.errors` (e.g., `u32!`) |

Using an unknown type name is a compile error (caught when the function definition is processed, before any call).

#### Type Coercion Rules

When an argument is passed to a typed parameter:

1. **Integer types.**  The argument must be an `IntValue`.  It is coerced to the target width following the integer overflow semantics: unsigned types wrap (modular arithmetic), signed types check and abort on overflow.  An `int` (arbitrary-precision) argument passed to a `u32` parameter is wrapped to 32 bits; the same value passed to an `i32` parameter must fit in the signed range or an `OverflowError` is raised.

2. **`bool`.**  The argument must be a `BoolValue`.  No implicit conversion from integers.

3. **`∅`.**  The argument must be `NoneValue`.

4. **Optional types (`T?`).**  Three cases:
   - `∅` passes through as `NoneValue`.
   - A `some(v)` value has its inner value coerced to `T`.
   - A plain (non-optional) value of type `T` is automatically wrapped in `some`.

5. **Expected types (`T?E`).**  Two cases:
   - An `ExpectedValue` passes through as-is (ok or err).
   - A plain value of type `T` is automatically wrapped in `ok`.

#### Examples

```
fn get_padded_byte data : byte[], pos : usize, total_size : usize → ?u8:
    ...

fn expand_s0 prev : u32 → int:
    (prev ↻ 7) ^ (prev ↻ 18) ^ (prev » 3)

fn maybe_use value : int? → ∅:
    ...
```

In `get_padded_byte`, the `data` parameter is typed as `byte[]` (a dynamic byte array), while the position and size parameters are enforced as `usize`.  In `expand_s0`, the `prev` parameter is coerced to `u32`, ensuring rotation operations use 32-bit semantics.  In `maybe_use`, the parameter accepts either a plain integer (auto-wrapped to `some`) or `∅`.

#### Design Rationale

Parameter type enforcement catches type errors early and enables the interpreter to coerce values to the correct width automatically.  Leaving the type annotation optional preserves the scripting-mode flexibility: untyped parameters accept any value, which is useful for generic functions and for parameters whose types are not yet part of the built-in set (such as user-defined structs or standard library objects like `Bytes`).

| Feature | Rust | Zig | Python | NGPL |
|---------|------|-----|--------|---------------|
| Parameter types | Required | Required | Optional (hints only) | Optional (enforced when present) |
| Coercion | No (explicit conversion) | No | N/A | Yes (integer widening) |
| Optional params | `Option<T>` | `?T` | `T \| None` | `T?` |
| Unknown type | Compile error | Compile error | Runtime (if checked) | Compile error |


### Parameter Mutability

Function parameters are **immutable by default**, just like `let` bindings.  Attempting to reassign a parameter inside the function body is an error:

```
fn broken(x : i32) → i32:
    x ← x + 1        // error: cannot assign to let variable 'x'
    x
```

To make a parameter mutable, use the `mut` type qualifier in the same position as for variable definitions:

```
fn increment(x : mut i32) → i32:
    x ← x + 1
    x
```

Parameters without a type annotation are also immutable — there is no way to mark an untyped parameter as mutable (add a type annotation if mutation is needed).

Immutability covers what the parameter names, not only the name, so writing to an element of an array parameter needs `mut` as much as reassigning it does:

```
fn broken(arr : i32[]) → ∅:
    arr[0] ← 9        // error: cannot assign to element of let variable 'arr'

fn fine(arr : mut i32[]) → ∅:
    arr[0] ← 9        // writes to this function's own copy
```

`mut` does not make the write visible to the caller: an array parameter is passed by value, so `fine` writes to its copy and the caller's array is unchanged.  Passing `&arr` is what shares the array — see [Call-by-Value and Call-by-Reference](#call-by-value-and-call-by-reference).

This follows Rust's convention where `fn foo(x: i32)` produces an immutable binding and `fn foo(mut x: i32)` produces a mutable one.  The design encourages writing functions that do not modify their inputs, making control flow easier to follow.

| Feature | Rust | Zig | C++ | Python | NGPL |
|---------|------|-----|-----|--------|------|
| Params mutable by default | No | Yes | Yes | Yes (rebinding) | No |
| Mutable param syntax | `mut x: T` | N/A | N/A | N/A | `x : mut T` |


### Call-by-Value and Call-by-Reference

By default, function parameters are passed **by value**.  For mutable compound values such as arrays, the interpreter creates a deep copy of the argument so that modifications inside the function do not affect the caller.  Scalar values (integers, floats, booleans, strings) are immutable and naturally passed by value without copying.

To pass a parameter **by reference**, prefix the type annotation with `&`.  A bare `&` lends the value for reading; `&mut` lends it for writing:

```
fn total(arr : &i32[]) → i32:              // may read
    arr[0] + arr[1]

fn fill_zeros(arr : &mut i32[]) → ∅:     // may write
    foreach i := 0…(arr.sizeof - 1):
        arr[i] = 0
```

`&` says where the value lives, not that the callee may change it.  Writing through one is an error:

```
fn broken(arr : &i32[]) → ∅:
    arr[0] = 99

error: cannot assign to element of borrowed variable 'arr'
```

This is the same distinction `foreach` draws with `&` and `&mut`, and the one `impl` methods draw with `&self` and `&mut self`.  Only `mut` grants the right to write, whether the value arrived by value or by reference; a by-value parameter needs `mut` for the same reason, the difference being only whose copy is written.

At the call site, the argument must also be prefixed with `&` to make the reference explicit:

```
let data : mut i32[] = [1, 2, 3]
fill_zeros(&data)
// data is now [0, 0, 0]
```

#### Semantics

- **By-value parameters** receive a deep copy of mutable data.  Changes to the parameter inside the function are local to that invocation and are not visible to the caller.
- **Shared by-reference parameters** (`&T`) receive a reference the callee may read but not write.
- **Mutable by-reference parameters** (`&mut T`) receive a reference the callee may write.  Assignments to the parameter, including element mutation, are visible to the caller after the function returns.
- Passing a non-reference argument to a `&`-parameter is a type error: *"parameter 'x' is by-reference, caller must pass &x"*.
- Passing a `&`-argument to a by-value parameter is a type error: *"parameter 'x' is by-value, caller must not pass a reference"*.

#### A Reshape Inherits `&` and `mut` from Its Source

A reshape does not copy.  The result shares the storage it was built from, and with it the access that storage was available under: reshaping something lent for reading yields a view that may be read, and reshaping something lent for writing yields one that may be written.  `⍴` changes the shape of a value, not the terms on which it is held.

| Source | Result |
|--------|--------|
| `&T[]` — lent for reading | may be read |
| `&mut T[]` — lent for writing | may be written, and the write reaches the source |
| a `let` binding | may be read |
| a `mut` binding | may be written |

Everything below follows from that one rule.  Because the properties are inherited rather than chosen, a view cannot be used to gain access its source did not have — which is what makes `&` and `mut` mean the same thing after a reshape as before it.

The rule also explains why a function that writes through a view of a parameter counts as modifying that parameter, and so does not draw the [unused-`mut` warning](#an-unused-mut-is-a-warning): the write reaches the parameter.

Because the access is inherited, a binding does not repeat it.  `let m := (2, 2) ⍴ a` may be written exactly when `a` may be, and saying `mut` as well states what is already true:

```
let a : mut i32[] = 4 ⍴ 0
let m : mut = (2, 2) ⍴ a

warning: 'm' is declared mut, but a reshape already carries the access of what
it was built from; naming a full type is what would change it
```

Naming a full type is how a binding says what it wants instead of what it was given, and that declaration is then the one that counts:

```
let m : mut i32[] = (2, 2) ⍴ a     // the type decides, not the source
```

The warning applies only where there is something to inherit: a reshape of a literal has no source binding, so `let m : mut = (2, 3) ⍴ 0` needs its `mut` and does not draw one.

Binding the result as `mut` would claim write access, so taking a mutable view of something that may only be read is rejected rather than merely redundant, at the binding:

```
fn broken(arr : &i32[]) → ∅:
    let m : mut = (2, 2) ⍴ arr

error: cannot take a mutable view of borrowed variable 'arr'
```

The binding is where this has to be caught.  Once the view exists it is a mutable local of its own, and a write through it carries no record of where its storage came from — checking the write would see only `m`, which is mutable, and allow it.  Refusing to create the view in the first place is what keeps `&` meaning what it says.

The same applies to any immutable source, not only a borrow: a `let` local and a by-value parameter are both rejected, naming their own kind.

A read-only view of a shared borrow is fine, since it hands out nothing the borrow did not already permit:

```
fn fine(arr : &i32[]) → i32:
    let m := (2, 2) ⍴ arr      // not mut
    m[0, 0]
```

As does a mutable view of something lent for writing:

```
fn also_fine(arr : &mut i32[]) → ∅:
    let m : mut = (2, 2) ⍴ arr
    m[0, 1] = 42                             // reaches the caller
```

#### Interaction with Reshape Views

When a by-reference array parameter is reshaped inside a function using `⍴`, the resulting view shares the caller's backing storage.  Modifications through the reshaped view propagate to the caller's array:

```
fn reshape_and_set(arr : &i32[]) → ∅:
    let m : mut = (2, 2) ⍴ arr
    m[0, 1] = 42

let a : mut i32[] = 4 ⍴ 0
reshape_and_set(&a)
// a[1] is now 42
```

With a by-value parameter, the deep copy ensures the caller's array is unaffected:

```
fn reshape_and_set_val(arr : i32[]) → ∅:
    let m : mut = (2, 2) ⍴ arr
    m[0, 1] = 99

let a : mut i32[] = 4 ⍴ 0
reshape_and_set_val(a)
// a[1] is still 0
```

#### Design Rationale

The `&` syntax follows Rust's convention of explicit reference passing.  Requiring `&` at both the declaration and the call site ensures that side effects through parameters are always visible to the reader — a function call without `&` arguments can never mutate the caller's state (assuming purity constraints are met).  This is consistent with NGPL's design goal of making the programmer's intent explicit.

| Feature | Rust | Zig | C++ | NGPL |
|---------|------|-----|-----|------|
| Default passing | By value (move) | By value / by pointer | By value | By value (deep copy) |
| Reference syntax | `&` / `&mut` | `*T` pointer | `T&` / `const T&` | `&T` |
| Call-site marker | Automatic (borrow) | `&var` | None | `&var` |
| Mutable ref | Requires `&mut` | `*T` | `T&` | `&T` (always mutable) |


### Block Scoping: Braces and Layout

Blocks of statements — function bodies, if/elif/else branches, while loop bodies — can be delimited in two ways.  Both styles are fully interchangeable and can be freely mixed within a single source file or even within a single function.

#### Brace-Delimited Blocks

The traditional approach uses `{` and `}` to delimit blocks:

```
fn abs x : int → int {
    if x < 0 { return -x; }
    x
}
```

Braces enclose zero or more statements.  Statements are separated by newlines or semicolons.  Indentation inside braces is not significant — it is conventional but not enforced by the parser.

#### Layout-Driven Blocks

A colon `:` at the end of a construct header introduces a layout-driven block, where indentation determines the block's extent:

```
fn abs x : int → int:
    if x < 0: return -x
    x
```

The rules are:

1. **Block introduction.**  A `:` after a function signature, `if`/`elif`/`else`, or `while` opens a layout block.

2. **Indentation.**  The first indented line after `:` establishes the block's indent level.  All subsequent lines at that level (or deeper) are part of the block.  A line at a shallower level ends the block.

3. **Uniform indentation character.**  Within a file, indentation must use either all spaces or all tabs — mixing is a lexer error.  This matches Python 3's rule.

4. **Single-line form.**  A statement on the same line as `:` is a single-statement block:
   ```
   if x < 0: return -x
   ```

5. **Line continuation.**  A trailing binary operator (`+`, `-`, `*`, `/`, `%`, `|`, `&`, `^`, `<<`, `>>`, `«`, `»`, `↺`, `↻`, `==`, `!=`, `<`, `>`, `<=`, `>=`, `??`, `←`, `and`, `or`) or a trailing `=` (in variable definitions) signals that the expression continues on the next line.  The indentation of the continuation line does not create a new block:
   ```
   W[j] ← W[j - 16] + expand_s0(W[j - 15]) +
           W[j - 7] + expand_s1(W[j - 2])
   ```

6. **Nesting suppression.**  Inside parentheses `()` and brackets `[]`, indentation changes are ignored — no block boundaries are introduced.  This allows multi-line function arguments and array literals to be freely indented.

#### Mixed Mode

Brace and layout blocks can be mixed freely.  A function body can use `:` while an inner `if` uses `{ }`, or vice versa:

```
fn mixed x : int → int:
    if x > 10 {
        return x - 10;
    }
    x

fn mixed2 x : int → int {
    if x > 10:
        return x - 10
    x
}
```

This flexibility allows programmers to choose the style that best fits each situation — layout for clean, short blocks; braces for complex nesting or when explicit delimiters improve readability.

#### Design Rationale

| Feature | Python | Haskell | Rust | NGPL |
|---------|--------|---------|------|---------------|
| Layout blocks | Required (no braces) | Optional (`where`, `let`, `do`) | No | Optional |
| Brace blocks | No | Optional | Required | Optional |
| Mixed mode | No | Yes | No | Yes |
| Indent char | Spaces only (tabs allowed but not mixed) | Spaces only | N/A | Spaces or tabs (not mixed) |
| Block start | `:` | layout keywords | `{` | `:` or `{` |

The dual-mode approach draws from Haskell's optional layout rule while using Python's `:` syntax for familiarity.  The key advantage over Python is that braces remain available — useful for single-line blocks, machine-generated code, and situations where explicit delimiters reduce ambiguity.  The key advantage over Rust is that the common case of simple, sequential blocks needs no closing delimiter.


### While Loop

The plain form tests an expression each time round:

```
while n < 4:
    n ← n + 1
```

#### Binding Form

A `while` may also name a variable, using the same `:=` as `foreach`:

```
while e := it.next():
    use(e)
```

The expression is evaluated afresh at the start of every iteration, bound to the name, and the bound value is what decides whether the body runs.  This is `foreach` applied to a sequence produced a step at a time rather than known up front — which is exactly what an iterator is.

Without it the same loop has to call `next()` twice and keep the variable alive outside the loop that owns it:

```
let e : mut = it.next()
while e:
    use(e)
    e ← it.next()
```

The repetition is the problem: the two calls must stay identical, and the one at the bottom is easy to forget or to place inside a conditional by accident, either of which loops for ever.  The binding form has one call and no way to omit it.

A type may be given, as for a `foreach` variable:

```
while e : int = it.next():
    total ← total + e
```

#### The Name Holds the Value, Not the Optional

The body runs only when a value arrived, so inside it the name is bound to the value itself rather than to the optional that carried it.  `e` above is an element, not something that has to be unwrapped first:

```
while e := it.next():
    total ← total + e         // an integer, added directly
```

This is Rust's `while let Some(e) = it.next()` without the pattern: the shape of the loop already says that the body is the case where a value was there, so restating it in every loop adds nothing.

The rule holds for every operation that answers with an optional, not only iterators:

```
while x := v.pop():                 // x is the popped element
while name := std.env.get(key):     // name is the value of the variable
```

After the loop the name holds `∅` — the value that ended it.

#### Writing Back Through a `mut` Binding

A binding declared `mut` names the element rather than a copy of it, so assigning to it writes into the container:

```
let v : mut i32[] = [1, 2, 3, 4]
let it : mut = v.iterate()
while e : mut = it.next():
    e ← e + 1
// v is now [2, 3, 4, 5]
```

The two forms differ in exactly this, which their types state:

```
while e := it.next():          // @typeof(e) is "i32" -- a copy
while e : mut = it.next():     // @typeof(e) is "&mut i32" -- the element
```

A plain binding leaves the container untouched, so a loop that only reads cannot change anything by accident, and one that means to change something has to say so.

`mut` is rejected where there is nothing to write back to.  `v.pop()` removes the element and hands over the value itself; there is no longer a place in the container for it, so:

```
while x : mut = v.pop():

error: 'x' is declared mut, but the loop produces values that cannot be
written back
```

This is the same distinction `&` and `&mut` draw for `foreach`, reached from the other direction: there the borrow is written on the container, here the mutability is written on the binding, because a `while` has no container in the syntax to write it on.

#### The Bound Name

The name is rebound at the start of each iteration, so assigning to it inside the body would be overwritten before it could be read.  It is therefore frozen, exactly as a `foreach` variable is:

```
while e := it.next():
    e ← 99

error: cannot assign to while variable 'e'
```

The value is tested with the ordinary rules, so an optional tests presence and an element of `0` does not end the loop — see [Optionals in a Boolean Context](#optionals-in-a-boolean-context).  A plain value is tested on its own terms, so `while remaining := n:` runs until `n` reaches zero.

#### Telling the Two Forms Apart

Both forms begin with an identifier followed by a colon, since `while e:` is a plain condition on `e` and `while e := ...` is a binding.  What comes after the colon decides: `=` means the untyped binding, and a type name followed by `=` means the typed one.

An inline body that is itself an assignment — `while e: x = 5` — has the same shape as a typed binding and is rejected.  Written as an indented block it is unambiguous:

```
while e:
    x = 5
```

#### Comparison with Other Languages

| Language | Loop while a value keeps arriving |
|----------|-----------------------------------|
| C | `while ((e = next()) != NULL)` |
| C++17 | no `while` form; `if (auto e = f(); e)` for the single test |
| Rust | `while let Some(e) = it.next()` |
| Go | `for e := next(); e != nil; e = next()` |
| Zig | `while (it.next()) \|e\|` |
| Python | `while (e := it.next()) is not None` |
| NGPL | `while e := it.next():` |

Rust and Zig bind and test in one construct, as this does.  C's idiom is the same shape but needs the assignment parenthesized and compared explicitly, which is the classic source of `=` written where `==` was meant.  Go has no binding `while` at all, so the call appears twice, which is the repetition this form removes.


### Foreach Loop

The `foreach` loop iterates over **ranges** and **containers**, binding one or more loop variables that are constant within the loop body.

#### Syntax

```
foreach var1 [: type1] [, var2 [: type2] ...] := expr1 [, expr2 ...] block
```

The `:=` separates the variable list from the iterable expressions, consistent with variable definitions using `let x : mut = expr`.  When a type annotation is present on the last variable, the `:` is consumed by the type syntax, so only `=` follows (e.g., `foreach k : u32 = 0…3:`).  The block uses either `:` (layout) or `{ }` (braces), like all other block constructs.

#### Ranges

A range expression `start…end` (using the `…` character) generates an inclusive sequence of integers:

```
foreach i := 1…10:
    std.print(i)            /* prints 1, 2, 3, ..., 10 */

foreach j := 5…1:
    std.print(j)            /* prints 5, 4, 3, 2, 1 */
```

The direction is determined by comparing `start` and `end`: ascending if `start ≤ end`, descending otherwise.  The type of the loop variable is **untyped int** — its actual integer width is decided by the context in which it is used, not committed to `int` at the range site.

#### Stepped Ranges

A three-part range `start…step…end` iterates from `start` to `end` (inclusive) with the given step size:

```
foreach i := 0…2…10:
    std.print(i)            /* prints 0, 2, 4, 6, 8, 10 */

foreach j := 1…3…10:
    std.print(j)            /* prints 1, 4, 7, 10 */
```

The step can be negative for descending iteration:

```
foreach k := 10…-3…0:
    std.print(k)            /* prints 10, 7, 4, 1 */
```

The step must be a non-zero integer.  The end bound is inclusive: the last value produced is the largest (or smallest, for negative step) value in the sequence that does not exceed the bound.  When the step does not evenly divide the range, the final value may be less than `end`:

```
foreach i := 0…3…10:
    std.print(i)            /* prints 0, 3, 6, 9 (not 10) */
```

Stepped ranges are particularly useful for block-oriented processing:

```
foreach blk_off : usize = 0…64…(total_size - 1):
    /* process 64-byte blocks starting at blk_off */
```

| Syntax | Semantics |
|--------|-----------|
| `a…b` | Inclusive range from `a` to `b`, step 1 (or -1 if `a > b`) |
| `a…s…b` | Inclusive range from `a` to `b`, step `s` |

#### Typed Variables

Loop variables can carry type annotations to coerce range values to a specific width:

```
foreach k : u32 = 0…255:
    ...
```

#### Multiple Variables and Iterables

When the number of variables matches the number of expressions, each variable iterates over its corresponding iterable:

```
foreach i, j := 1…5, 10…14:
    /* i takes values 1,2,3,4,5 and j takes values 10,11,12,13,14 */
    ...
```

#### Wrapping Shorter Ranges

The loop runs for as many iterations as the **longest** iterable.  Shorter iterables wrap around from the beginning:

```
foreach i, j := 1…6, 10…12:
    /* i: 1, 2, 3, 4, 5, 6          (6 iterations) */
    /* j: 10, 11, 12, 10, 11, 12    (wraps after 3) */
    ...
```

#### Single Variable with Multiple Iterables — Tuples

When there is exactly **one** variable but **multiple** iterable expressions, the variable receives a **tuple** containing one element from each iterable at the current position:

```
foreach pair := 1…3, 10…12:
    std.print(pair[0])      /* 1, 2, 3 */
    std.print(pair[1])      /* 10, 11, 12 */
```

Tuple elements are accessed by integer index (`pair[0]`, `pair[1]`).  In the future, access by unique type name will also be supported when the element types are distinct.  Wrapping rules apply to each iterable independently.

#### Container Iteration

In addition to ranges, `foreach` iterates directly over array elements:

```
let data : mut = [10, 20, 30, 40]
let total : mut = 0
foreach val := data:
    total ← total + val
/* total is 100 */
```

This works with any array, including dynamic arrays passed as parameters:

```
fn sum_bytes data : byte[] → int:
    let total : mut = 0
    foreach b := data:
        total ← total + b
    total
```

For dynamic arrays, `foreach` uses the array's `.sizeof` to determine the iteration count.

#### Constant Loop Variables

Loop variables are **constant** within the body — they cannot be reassigned:

```
foreach i := 1…5:
    i ← i + 1          /* ERROR: cannot assign to foreach variable 'i' */
```

Redefinition with `let mut` or `let` is permitted but produces a **warning**.  The new variable shadows the loop variable for the remainder of the iteration:

```
foreach i := 1…3:
    let i : mut = 99         /* WARNING: redefinition of foreach variable 'i' */
    /* i is 99 here, not the loop counter */
```

This distinction exists because shadowing is a common intentional pattern (e.g., transforming a loop variable into a different form), while assignment would silently alter the loop's iteration semantics.  The warning ensures the programmer is aware of the shadowing.

#### Examples

Accumulate a sum:
```
let sum : mut = 0
foreach i := 1…100:
    sum ← sum + i
/* sum is 5050 */
```

Two-variable loop with wrapping:
```
foreach row, col := 0…2, 0…3:
    /* row wraps: 0,1,2,0  for 4 iterations (longest range) */
    /* col runs:  0,1,2,3 */
    ...
```

Tuple destructuring by index:
```
foreach point := [1,2,3], [10,20,30]:
    let x : mut = point[0]
    let y : mut = point[1]
```

#### Design Rationale

| Feature | Python | Rust | Zig | NGPL |
|---------|--------|------|-----|---------------|
| Iteration keyword | `for` | `for` | `for` | `foreach` |
| Range syntax | `range(1, 11)` | `1..=10` | `0..10` | `1…10` (inclusive) |
| Stepped range | `range(0, 11, 2)` | `(0..=10).step_by(2)` | N/A | `0…2…10` |
| Multiple iterables | `zip(a, b)` | `a.zip(b)` | N/A | built-in with wrapping |
| Tuple binding | destructuring | destructuring | N/A | single let → tuple |
| Loop binding mutability | mutable | immutable | N/A | immutable |
| Shorter-range behavior | `zip` truncates | `zip` truncates | N/A | wraps around |

The wrapping behavior for shorter ranges is deliberate: it enables patterns like cycling through a palette or repeating a short sequence across a longer one, which are common in array programming languages like APL.  Languages that truncate to the shortest require explicit repetition; wrapping makes the common case trivial.


#### Enumerate

The `enumerate(container)` built-in wraps an iterable so that `foreach` yields `(index, value)` tuples, with the index starting at 0:

```
foreach pair := enumerate([10, 20, 30]):
    std.print(pair[0], pair[1])      // 0 10, 1 20, 2 30
```

With two loop variables, the tuple is destructured automatically:

```
foreach i, v := enumerate([10, 20, 30]):
    std.print(i, v)                  // 0 10, 1 20, 2 30
```

`enumerate` works with arrays, ranges, and any other iterable.  Using `enumerate` outside a `foreach` context is an error.

| Feature | Python | Rust | Zig | NGPL |
|---------|--------|------|-----|---------------|
| Enumerate | `enumerate(x)` | `x.iter().enumerate()` | N/A | `enumerate(x)` |
| Destructuring | `for i, v in enumerate(x)` | `for (i, v) in x.enumerate()` | N/A | `foreach i, v := enumerate(x)` |


### Borrowing in a Foreach Loop (`&` and `&mut`)

Iterating an array ordinarily gives the loop a copy of each element, so the loop variable is frozen and assigning to it is rejected — writing to a copy that is about to be discarded is a mistake, not an intention.  Prefixing the container with `&` or `&mut` says what the loop wants to do with the elements instead.

#### `&mut` — Lending for Writing

```
let nums : mut = [1, 2, 3]
foreach x := &mut nums:
    x ← x + 1
// nums is now [2, 3, 4]
```

Under `&mut` the loop variable *refers to* the element rather than holding a copy of it.  Reading it gives the element's value, and assigning to it writes into the array.  This is the one kind of loop variable that may be assigned to, precisely because the assignment goes somewhere that outlives the iteration.

Several containers may be lent at once, one variable each:

```
foreach x, y := &mut a, &mut b:
    x ← x + 1
    y ← y + 1
```

#### `&` — Lending for Reading

```
let total : mut = 0
foreach x := &nums:
    total ← total + x
```

A shared borrow also refers to the element rather than copying it, but it may only be read.  Assigning to the loop variable is an error:

```
foreach x := &nums:
    x ← x + 1

error: cannot assign to borrowed variable 'x'
```

The diagnostic differs from the one for a plain `foreach`, which reports a *foreach* variable, because the programmer has said something different: with `&` they asked for a borrow and are being told which kind they took, rather than being told that loop variables are not assignable at all.

#### The Type of the Loop Variable

The three forms differ in the type they give the loop variable, and `@typeof` reports it:

```
foreach a := nums:              // @typeof(a) is "int"
foreach b := &nums:             // @typeof(b) is "&int"
foreach c := &mut nums:         // @typeof(c) is "&mut int"
```

The referent type follows the elements, so borrowing a `str[]` gives `&str` and `&mut str`.

Reading a borrowed variable yields the element, not the reference — `b + 1` is an integer addition, with no dereferencing step to write.  The reference shows only in the type, which is where it matters: it is what distinguishes a loop that may write to the container from one that may not.

Because the language has no literal for a reference type, a type is compared against its written name:

```
static_assert_eq(@typeof(c), "&mut int")
```

#### What May Be Lent

A mutable borrow is a promise to write, so it may only be taken of something writable.  Lending an immutable binding for writing is rejected where the borrow is taken, not where the write happens:

```
let nums := [1, 2, 3]
foreach x := &mut nums:
    x ← x + 1

error: cannot mutably borrow let variable 'nums'
```

Both forms currently require an array.  Ranges and tuples have no elements to lend a reference to.

Destructuring a borrowed container is rejected, because it is not yet decided whether the parts or the whole would be lent:

```
foreach a, b := &mut pairs:

error: foreach over a borrow needs one variable per borrowed container
```

#### Why the Distinction Is Explicit

A language could make `foreach x := nums` write through whenever the loop assigns to `x`, and many do.  Requiring `&mut` states at the top of the loop that the container is about to change, so a reader knows before reading the body — and it makes the far more common read-only loop say so as well.  It also leaves `foreach x := nums` free to mean the copy it appears to mean.

The borrow is written on the container rather than on the loop variable because it is the container that is being lent.  `foreach x := &mut nums` reads as "for each x in a mutable borrow of nums", which is what happens.

#### Comparison with Other Languages

| Language | Read-only iteration | Mutating iteration |
|----------|--------------------|-------------------|
| C++ | `for (auto x : v)` | `for (auto& x : v)` |
| Rust | `for x in &v` | `for x in &mut v` |
| Go | `for _, x := range v` (copy) | index and assign `v[i]` |
| Zig | `for (v) \|x\|` | `for (v) \|*x\|` |
| Python | `for x in v` (copy for numbers) | index and assign `v[i]` |
| NGPL | `foreach x := v` or `&v` | `foreach x := &mut v` |

The syntax is Rust's, and so is the reasoning: the two borrows are different enough that spelling them differently is worth the characters.  C++ makes the same distinction on the loop variable rather than the container, which reads as a property of `x` when it is really a statement about `v`.  Go and Python offer no borrowing form at all, so a mutating loop has to index the container manually and the connection between the index and the element is left to the reader.


### Anonymous Functions (Lambdas)

Anonymous functions are introduced with the `λ` (U+03BB, GREEK SMALL LETTER LAMDA) keyword.

#### Syntax

```
λ param1 : type1 [, paramN : typeN] [|capture1 [, captureN]|] → ret_type : body
```

- **Parameters**: zero or more comma-separated `name : type` pairs.  Type annotations are mandatory, using the same syntax as function parameters.
- **Return type**: mandatory, specified with `→` (or `->`) followed by a type name.  The `?` and `!` suffixes for optional and error types are supported (e.g., `→ int?`, `→ int!`).
- **Capture list**: optional, enclosed in `|…|`.  Lists the external variables that the lambda body may access.  Must contain at least one name; an empty capture list `||` is a parse error.  Omit the capture list entirely when no captures are needed.
- **Body**: either a single expression after the colon, or a multi-statement block using the same syntax as function bodies (layout-driven with `:` and indentation, or brace-delimited with `{ … }`).  In a multi-statement body the value of the last expression is the return value; explicit `return` is also supported for early exit.

#### Multi-Statement Lambda Bodies

When a lambda body requires more than one expression, use the usual block syntax:

```
// Layout-driven (indented block)
let f : mut = λx : int → int:
    let y : mut = x * 2
    y + 1

// Brace-delimited
let g : mut = λx : int → int: {
    let y : mut = x + 10;
    let z : mut = y * 2;
    z
}
```

Early return is supported inside multi-statement lambda bodies:

```
let clamp : mut = λx : int |lo, hi| → int:
    if x < lo:
        return lo
    if x > hi:
        return hi
    x
```

When passing a multi-statement lambda as a function argument, braces are required because indentation tracking is suppressed inside parentheses:

```
let result : mut = apply(λx : int → int: {
    let a : mut = x + 1;
    a * 2
}, 4)
```

#### Capture Rules

The lambda body has a restricted environment:

- **Built-in functions** (e.g., `assert`, `assert_eq`), **enum types**, and **module objects** (e.g., `std`) are always accessible without capture.
- **Non-replaceable user-defined functions** (the default) are always accessible without capture.  Since their binding is immutable, the lambda can safely reference them.
- **`@replaceable` functions** and **variables** must appear in the capture list to be used in the body.
- If no capture list is present (no `|…|` at all), the lambda cannot reference any capturable names from the enclosing scope.
- If a capture list is present but a referenced name is missing from it, a compile-time error is raised.

```
fn helper x : i32 → i32:
    x + 100

let offset : mut = 10
let f : mut = λx : i32 |offset| → i32: helper(x) + offset   // OK: helper is non-replaceable, offset is captured
let g : mut = λx : i32 → i32: helper(x)                     // OK: helper needs no capture
let h : mut = λx : i32 → i32: x + offset                     // ERROR: references 'offset' but has no capture list
```

#### Calling Lambdas

Lambdas are first-class values.  They can be assigned to variables, passed as arguments, and returned from functions.

```
let double : mut = λx : int → int: x * 2
assert_eq(10, double(5))
```

Immediate application uses parentheses around the lambda:

```
let result : mut = (λx : int → int: x + 1)(5)   // result is 6
```

#### Lambdas as Arguments and Return Values

```
fn apply f, x : i32 → i32:
    f(x)

fn make_adder n : i32:
    λx : int |n| → int: x + n

let add3 : mut = make_adder(3)
assert_eq(8, add3(5))
assert_eq(15, apply(λx : int → int: x * 3, 5))
```

#### Function Currying

Calling a function with fewer arguments than its parameter list produces a partially-applied lambda.  The provided arguments are captured automatically.

```
fn add a : i32, b : i32 → i32:
    a + b

let add5 : mut = add(5)                  // returns λb (partial add[5])
assert_eq(8, add5(3))
```

Multi-step currying is supported:

```
fn add3 a : i32, b : i32, c : i32 → i32:
    a + b + c

let f1 : mut = add3(1)                   // λb, c
let f2 : mut = f1(2)                     // λc
assert_eq(6, f2(3))               // 1 + 2 + 3
```

Lambdas themselves support partial application:

```
let mul : mut = λx : int, y : int → int: x * y
let triple : mut = mul(3)
assert_eq(15, triple(5))
```

#### The `@replaceable` Attribute

By default, functions are immutable bindings — once defined, their implementation cannot change.  Such functions are always accessible inside lambdas without being listed in the capture list, because the lambda's reference to the function can never become stale.

A function marked `@replaceable` can have its implementation swapped at runtime (see the language specification for function replacement).  Because its binding is mutable, a `@replaceable` function **must** be captured explicitly:

```
@replaceable
fn strategy x : i32 → i32:
    x * 2

// Must capture — strategy could change after the lambda is created
let f : mut = λx : i32 |strategy| → i32: strategy(x)

// ERROR: strategy is @replaceable and not captured
let g : mut = λx : i32 → i32: strategy(x)
```

This distinction ensures that lambdas with no capture list or an empty capture list are guaranteed to be pure with respect to user-defined state — they depend only on their parameters and immutable bindings.

#### Ignored Lambda Warning

A lambda value that is neither assigned to a variable nor returned produces a warning.  This catches accidental partial applications:

```
add(5)                             // WARNING: lambda value is not used
λx : int → int: x + 1             // WARNING: lambda value is not used
```

#### Design Rationale

| Feature | Haskell | Rust | Python | NGPL |
|---------|---------|------|--------|---------------|
| Lambda syntax | `\x -> x+1` | `\|x\| x+1` | `lambda x: x+1` | `λx : int → int: x+1` |
| Capture | implicit | explicit (`move`) | implicit | explicit (`\|…\|`) |
| Currying | automatic | no | no | automatic |
| Multi-expression body | no (one expr) | yes (block) | no (one expr) | yes (block or layout) |
| Unused lambda warning | no | yes (unused `Result`) | no | yes |

The explicit capture list follows the principle that a lambda's dependencies should be visible at the definition site.  Unlike Rust's closure inference, NGPL requires the programmer to declare what is captured — making the lambda self-documenting and preventing accidental capture of mutable state.

Automatic currying follows Haskell's model: every function of N parameters is conceptually a chain of N single-parameter functions.  This makes point-free style and function composition natural.


### Ranges as Values

Range expressions (`start…end` and `start…step…end`) are first-class values.  They can be stored in variables, passed as arguments, and iterated with `foreach`.

```
let r : mut = 1…10
foreach i := r:
    ...
```

Ranges bind tighter than comparison but looser than arithmetic:

```
let r : mut = 1 + 2 … 10 - 3             // equivalent to (1+2)…(10-3) = 3…7
```


### The `generate` Function

`generate` applies a function to each value in a range, collecting the results into an array.  It is the primary way to construct arrays from a mapping function.

#### Syntax

```
generate(func, range)
```

- **func**: any callable — a named function, a lambda, or a curried (partially-applied) function.
- **range**: a range value (`start…end` or `start…step…end`).
- **returns**: an array whose size equals the number of elements in the range.

#### Basic Usage

```
let squares : mut = generate(λx : int → int: x * x, 1…5)
// squares = [1, 4, 9, 16, 25]

fn double x : i32 → i32:
    x * 2

let doubled : mut = generate(double, 1…4)
// doubled = [2, 4, 6, 8]
```

#### With Currying

A curried function can be used as the mapping function:

```
fn multiply a : i32, b : i32 → i32:
    a * b

let tripled : mut = generate(multiply(3), 1…5)
// tripled = [3, 6, 9, 12, 15]
```

#### With Stepped and Descending Ranges

```
let evens : mut = generate(λx : int → int: x, 0…2…10)
// evens = [0, 2, 4, 6, 8, 10]

let desc : mut = generate(λx : int → int: x * x, 3…1)
// desc = [9, 4, 1]
```

#### With Captures

```
let offset : mut = 100
let arr : mut = generate(λx : int |offset| → int: x + offset, 1…3)
// arr = [101, 102, 103]
```

#### Returning ∅ is Invalid

The mapping function must not return ∅.  This is a runtime error because the result array cannot contain empty optional values:

```
generate(λx : int → ∅: ∅, 1…5)    // ERROR: function must not return ∅
```

#### Compile-time Optimization (Future)

When the range bounds are compile-time constants, the compiler can determine the array size statically and allocate a fixed-size array.  When the bounds are runtime values, the result is a dynamically-sized array.  In the prototype interpreter, all arrays are dynamically sized.

For higher-rank results (matrices, tensors), `generate` will accept multi-dimensional ranges and return objects of matching rank.  This is planned for future implementation.

#### Design Rationale

| Feature | Haskell | Python | Rust | APL | NGPL |
|---------|---------|--------|------|-----|---------------|
| Map+collect | `map f [1..n]` | `[f(x) for x in range(1,n+1)]` | `(1..=n).map(f).collect()` | `f⍳n` | `generate(f, 1…n)` |
| Result type | list | list | `Vec<T>` | array | array |
| None/null in result | allowed | allowed | `Option` in vec | N/A | error |

`generate` combines mapping and collection into a single operation, emphasizing the functional construction of arrays.  The prohibition on ∅ return values ensures the result array is dense — every element contains a meaningful value.  This matches the array programming tradition (APL, J, BQN) where arrays are always rectangular and fully populated.


### The Reshape Operator (`⍴`)

The reshape operator `⍴` (APL rho) creates arrays and tensors by reshaping data to specified dimensions.  The left operand defines the shape; the right operand provides the data, which is cycled if it contains fewer elements than needed.

#### Syntax

```
shape ⍴ data
```

- **shape**: an integer (vector result) or a tuple of integers (matrix/tensor result).
- **data**: a scalar, array, or range whose elements fill the result.
- **returns**: a new array (or nested array for matrices/tensors) of the specified shape.

#### Vectors

When the left operand is a single integer, the result is a one-dimensional array:

```
let zeros : mut = 64 ⍴ 0               // [0, 0, ..., 0] — 64 elements
let pattern : mut = 5 ⍴ [1, 2, 3]      // [1, 2, 3, 1, 2] — cycling
let first3 : mut = 3 ⍴ [10, 20, 30, 40, 50]  // [10, 20, 30] — truncating
```

The dimension can be a variable:

```
let n : mut = 100
let buf : mut = n ⍴ 0
```

When the right operand is a range, it is expanded before cycling:

```
let a : mut = 5 ⍴ (1…3)                // [1, 2, 3, 1, 2]
```

#### Matrices and Tensors

When the left operand is a tuple, the result is a nested array whose depth matches the number of dimensions:

```
let m : mut = (2, 3) ⍴ 0               // 2×3 matrix of zeros
let filled : mut = (2, 3) ⍴ [1, 2, 3, 4, 5, 6]
// filled[0] = [1, 2, 3]
// filled[1] = [4, 5, 6]

let cycled : mut = (3, 2) ⍴ [1, 2, 3, 4, 5]
// cycled[0] = [1, 2]
// cycled[1] = [3, 4]
// cycled[2] = [5, 1]  — cycling wraps around
```

Elements fill in row-major order, matching APL/BQN semantics.

#### Dimension Limit

The maximum number of dimensions is controlled by a global limit (`MAX_TENSOR_RANK`, default 8).  This same limit applies to all tensor operations in the language.  Exceeding it is a compile-time or runtime error:

```
let too_deep : mut = (1,1,1,1,1,1,1,1,1) ⍴ 0   // error if more than MAX_TENSOR_RANK dims
```

#### Array Bounds Checking

Arrays perform strict bounds checking on both reads and writes.  Accessing an index outside `0..length-1` is a runtime error:

```
let a : mut = [1, 2, 3]
let x : mut = a[3]             // error: array index 3 out of range (length 3)
a[⁻1] ← 4                // error: array index -1 out of range (length 3)
```

This replaces the earlier behavior where out-of-bounds writes silently extended the array.  To grow an array, use `⍴` to reshape it to the desired size:

```
let W : mut = 64 ⍴ generate(load_word, 0…15)   // extend 16-element result to 64
```

#### Multi-Dimensional Subscript

Nested arrays (matrices, 3D arrays, etc.) can be indexed with comma-separated indices inside a single pair of brackets instead of chaining multiple bracket pairs:

```
let m : mut = (2, 3) ⍴ [1, 2, 3, 4, 5, 6]
let x : mut = m[1, 2]           // 6 — equivalent to m[1][2]

m[0, 1] ← 42              // write access
```

This extends to higher dimensions:

```
let a : mut = (2, 3, 4) ⍴ (1…24)
let y : mut = a[1, 2, 3]        // 24 — equivalent to a[1][2][3]
a[1, 0, 1] ← 55            // write access
```

Each index is validated against the array at that nesting level.  Out-of-bounds access at any dimension is a runtime error.  Attempting multi-dimensional subscript on a non-nested value (e.g., `flat_array[0, 0]`) is a type error.

The chained bracket syntax (`m[i][j]`) remains valid and is equivalent — multi-dimensional subscript is syntactic convenience, not a separate operation.

#### Index Unit Requirements

Array indices follow a tiered rule based on the integer's type status:

1. **Untyped integer constants** (literals like `0`, `42`, expressions that remain uncoerced) are accepted as indices for any array without unit annotation.
2. **Typed integers** (`i32`, `u32`, `u32fast`, `usize`, etc.) must carry a unit matching the array kind:
   - **`byte[]` / `u8[]` arrays** require unit **`byte`** (`B`).
   - **All other arrays** require unit **`ptrdiff`**.
3. **Wrong units** are always rejected regardless of whether the integer is typed or untyped.

```
let arr : mut = [10, 20, 30]
let x : mut = arr[0]                // OK — untyped integer constant

let idx : mut i32 = 1
let z : mut = arr[idx]              // error: typed integer without unit
let idx2 ¤ptrdiff : mut i32 = 1
let w : mut = arr[idx2]             // OK — variable carries ptrdiff unit

let buf : mut u8[4] = 0
let b : mut = buf[0]                // OK — untyped integer constant
```

Units are attached at the point of declaration — variable definitions, or function parameters:

```
fn safe_get arr : i32[], idx ¤ptrdiff : i32 → i32?:
    catch:
        arr[idx]             // OK — idx carries ptrdiff from declaration

fn read_byte data : byte[], off ¤byte : usize → u8:
    data[off]                // OK — off carries byte from declaration
```

The `.sizeof` property returns the appropriate unit automatically (`ptrdiff` for general arrays, `byte` for byte arrays), so loop bounds derived from `.sizeof` produce correctly-typed indices:

```
let arr : mut = [1, 2, 3, 4]
let total : mut = 0
foreach i := 0…arr.sizeof - 1:       // i carries ptrdiff unit
    total ← total + arr[i]           // OK — i already has ptrdiff
```

When a loop variable is explicitly typed, a unit-carrying copy is needed for indexing:

```
foreach j : u32fast = 16…63:
    let ji ¤ptrdiff : mut = j
    W[ji] ← W[ji - 16] + expand(W[ji - 2])
```

Alternatively, omitting the type annotation keeps the loop variable untyped, which needs no unit:

```
foreach j := 16…63:
    W[j] ← W[j - 16] + expand(W[j - 2])
```

Slice access (`arr[start…end]`) follows the same rule: both bounds must carry the correct unit when typed, or be untyped constants.

Tuple indexing is not affected — tuples accept bare integer indices without unit annotation (`pair[0]`, `pair[1]`).

**Rationale.**  The unit requirement catches a category of bugs that arise when byte offsets are used where element indices are expected (or vice versa).  Untyped integer constants are exempt because they appear overwhelmingly as literal subscripts (`arr[0]`, `arr[2]`) where the intent is unambiguous and requiring annotation would add noise without safety benefit.  Typed integers, by contrast, often originate from computations or parameters where the domain (byte offset vs. element index) is not obvious from context — the unit must be attached at the point of declaration (`let idx ¤ptrdiff : mut = n` or `param ¤byte : type`), not at the subscript site.

#### Arithmetic Unit Enforcement

When one operand of a binary operation carries a unit and the other does not, the rules depend on the operation and the non-unit operand's type status:

**Additive operations** (`+`, `-`) and **comparisons** (`==`, `!=`, `<`, `>`, `<=`, `>=`):
- **Untyped integer constants** are accepted — the result inherits the unit of the unit-bearing operand (for `+`/`-`) or produces a boolean (for comparisons).
- **Typed integers** without a unit are rejected.  The programmer must attach the matching unit at the declaration site.

```
let a ¤ptrdiff : mut i32 = 5
let b : mut i32 = 3

let x : mut = a + 2         // OK — untyped constant, result is 7 ¤ptrdiff
let y : mut = a + b         // error: cannot + unit ptrdiff with typed integer i32
let z : mut = a == 5        // OK — untyped constant comparison
let w : mut = a < b         // error: cannot compare unit ptrdiff with typed integer i32
```

**Multiplicative operations** (`*`, `/`, `%`) allow mixing freely — a typed integer without unit acts as a dimensionless scalar:

```
let a ¤byte : mut i32 = 4
let b : mut i32 = 3

let x : mut = a * b         // OK — result is 12 ¤byte (scalar multiplication)
let y : mut = b * a         // OK — result is 12 ¤byte
```

**Rationale.**  Addition and comparison only make physical sense between quantities of the same dimension.  A typed integer without a unit is ambiguous — it might be a byte offset, an element count, or something else entirely.  Multiplication by a scalar, on the other hand, is always dimensionally valid (scaling).  Untyped constants are exempt because their use as small literal adjustments (`offset + 1`, `count - 1`) is unambiguous and pervasive.

#### Operator Precedence

`⍴` binds tighter than arithmetic (`+`, `-`, `*`, `/`) but looser than unary operators (`-x`, `~x`).  This means:

```
3 * 4 ⍴ 0     // 3 * [0, 0, 0, 0] — reshape first, then multiply
2 + 3 ⍴ 5     // 2 + [5, 5, 5]    — reshape first, then add
```

#### Design Rationale

| Feature | APL/BQN | Python | Rust | NGPL |
|---------|---------|--------|------|---------------|
| Reshape | `n ⍴ data` | `numpy.reshape` | N/A | `n ⍴ data` |
| Fill mode | cycle | error on mismatch | N/A | cycle |
| Bounds check | implicit | `IndexError` | panic | `IndexError` |
| Syntax | glyph | method | method | glyph |

The APL tradition uses `⍴` both monadically (query shape) and dyadically (reshape).  NGPL currently implements only the dyadic form.  The monadic form (returning the shape of an array) may be added in future.

The cycling semantics follow APL: when the data has fewer elements than the result requires, elements are reused from the beginning.  This makes `n ⍴ scalar` a natural way to create filled arrays, and `n ⍴ array` extends arrays without requiring explicit concatenation.


### Array Member Functions

Arrays carry five member functions for growing, shrinking, and reading them.  The set and the semantics are Rust's `Vec`:

| Function | Result | Description |
|----------|--------|-------------|
| `push(v)` | `∅` | Append `v` to the end |
| `pop()` | `T?` | Remove and return the last element, or `∅` when empty |
| `insert(i, v)` | `∅` | Insert `v` at index `i`, shifting later elements right |
| `remove(i)` | `T` | Remove and return the element at `i`, shifting later ones left |
| `get(i)` | `T?` | The element at `i`, or `∅` when there is none |

```
let v : mut = [1, 2, 3]
v.push(4)               // [1, 2, 3, 4]
v.pop()                 // 4, leaving [1, 2, 3]
v.insert(0, 0)          // [0, 1, 2, 3]
v.remove(1)             // 1, leaving [0, 2, 3]
v.get(0)                // 0
v.get(99)               // ∅
```

`insert` accepts an index equal to the length, which appends; anything beyond that is an error.

#### Which Failures Are Optionals

The five split into two groups, on a distinction worth stating because it decides how a caller has to write the call.

`pop` and `get` answer with an optional.  Asking for an element that may not be there is an ordinary thing for a correct program to do — draining a queue until it is empty, or looking up an index that came from outside — so the empty answer is a result, not a failure:

```
let last : mut = v.pop() ?? 0
let first : mut = v.get(0) ?? ⁻1
```

`insert` and `remove` raise instead.  An index the array does not have means the program has lost track of its own length, and there is no sensible value to return in its place — `remove` would have to invent an element.  Rust reaches the same split for the same reason, with `Option` for `pop` and `get` and a panic for `insert` and `remove`.

Note that `get` is the bounds-checked reader and the subscript is not: `v[9]` on a three-element array is still an error.  The two coexist deliberately, because an index the program believes is valid and an index it is testing are different situations, and writing them the same way would hide which one is meant.

#### Indices

An index passed to `get`, `insert`, or `remove` follows the same unit rule as a subscript: a byte array wants a `¤byte` index, anything else a `¤ptrdiff` one, and an untyped integer constant is always accepted.

```
let bytes : mut = std.bytes("abc")
bytes.get(1¤byte)        // 98
bytes.get(1¤count)       // error: array index requires unit B, got count
```

A value that is pushed or inserted takes the array's element type, exactly as an assignment through a subscript would.

#### Fixed-Size Arrays

An array whose type names a length — `i32[3]` rather than `i32[]` — keeps that length for as long as it exists.  The four resizing operations are errors on one:

```
let v : mut i32[3] = [1, 2, 3]
v.push(4)

error: push: cannot resize a fixed-size array; its type says it holds 3 elements
```

The length is in the type precisely so that a reader knows how much is there without tracing where the value came from; an array that could grow would make the type a lie.  `get` and element assignment are unaffected — only the length is fixed, not the contents.

The length travels with the value, so a copy of a fixed-size array is still fixed:

```
fn f(a : mut i32[3]) → ∅:
    a.push(4)                   // still an error, on this function's own copy
```

Assigning to a dynamic type produces a dynamic array, since the target type decides:

```
let f : mut i32[3] = [1, 2, 3]
let d : mut i32[] = f           // d may grow; f may not
```

#### Passing a Fixed Array

A by-value parameter takes a copy, and the copy has the parameter's shape — a `mut T[]` parameter yields a dynamic array whatever it was handed, which is the same conversion `let d : mut i32[] = f` performs.  A fixed array may therefore be passed to one, and the callee may grow its own copy:

```
fn grows(a : mut i32[]) → ∅:
    a.push(4)                   // grows the copy

let f : mut i32[3] = [1, 2, 3]
grows(f)                        // fine; f is still three elements
```

`&mut T[]` is a different matter.  There is no copy, so the callee would change the length of the caller's own array, which a fixed one cannot allow:

```
fn grows(a : &mut i32[]) → ∅:
    a.push(4)

grows(&f)

error: grows: parameter 'a' is a by-reference mutable 'i32[]', whose length the
function may change, but the argument is a fixed-size array of 3 elements
```

Refusing at the call matters here.  Without it the call succeeds and the failure appears inside `grows`, blaming `a` for being fixed — a parameter whose own type says `i32[]` and whose body is written exactly as that type allows.  The mistake is the caller's, and that is where it is reported.

| Parameter | Fixed argument | Why |
|-----------|---------------|-----|
| `i32[]` | accepted | immutable, so the length is never changed |
| `mut i32[3]` | accepted | a copy, and the length matches |
| `mut i32[]` | accepted | a copy, which the parameter's type makes dynamic |
| `&mut i32[]` | refused | no copy, and the caller's length is not open |

#### Mutating an Immutable Binding

`push`, `pop`, `insert`, and `remove` change the array, so they follow the rule that [writing an element](#what-immutability-covers) does: a binding that cannot be reassigned cannot have its contents rearranged either.

```
let v := [1, 2]
v.push(3)

error: push: cannot modify let variable 'v'
```

The same holds for a shared borrow, a `foreach` variable, and any other immutable binding, each named by its own kind.

#### Views

A view borrows a window into another array's storage, so it has no length of its own to change.  `push`, `pop`, `insert`, and `remove` on one are errors; `get` is not, since reading a view is what a view is for.

#### Slicing a Dimension

A range in a subscript selects part of a dimension.  `v[1…3]` takes three elements, and a matrix takes one spec per dimension, each of which is a point or a range:

```
let m := (3, 4) ⍴ (1…12)
m[1]              // a whole row: 4 elements
m[1, 0…2]         // part of that row: 3 elements
m[0…1, 2]         // part of a column: 2 elements
m[0…1]            // two whole rows
m[0…1, 1…2]      // a block: 2 rows of 2
```

What a slice shares follows from what it had to build.  Selecting along one dimension hands back the rows themselves, so writing through the result reaches the array the matrix was built from.  Narrowing a row cannot hand back that row, so it builds a new one and the result is a copy:

```
let a : mut i32[] = 12 ⍴ 0
let m := (3, 4) ⍴ a

let r : mut = m[1]           // a whole row, shared
r[0] = 55                    // a[4] is now 55

let b : mut = m[0…1, 1…2]   // narrowed, so copied
b[0][0] = 77                 // a is unchanged
```

A one-dimensional slice narrows by definition, so `v[1…3]` is always a copy.

Unlike a reshape, a slice does not inherit `mut` from its source: the binding above says `mut` for itself.

#### Passing Part of an Array

A slice is an argument like any other, and the parameter sees the length of the range rather than the length of what it was cut from.  A fixed-size parameter therefore checks the range:

```
fn sum3(a : i32[3]) → i32:
    a[0] + a[1] + a[2]

let v : i32[] = [10, 20, 30, 40, 50, 60]
sum3(v[1…3])        // ok: the range is 3 long
sum3(v[1…4])        // error: got array of length 4
```

A range keeps the dimensions it does not name, so slicing a matrix along one dimension leaves a matrix.  Two rows of a 3×4 are a 2×4, not two elements, and a parameter naming one dimension does not take it however many rows were selected:

```
fn rows2(m : i32[2]) → i32:
    m.sizeof

rows2(m[0…1])       // error: expected i32[2] (1 dimension), got a 2×4 array
rows2(m[0…1, 1…2])  // error: got a 2×2 array
```

Reaching one dimension takes a point rather than a range on the others, which is what `m[1]` and `m[1, 0…2]` do above.  A parameter that means to take the matrix says so with a matrix type, described next.

#### Array Types

An array type names one entry per dimension, so the rank is written down rather than inferred:

| Type | Meaning |
|------|---------|
| `i32[]` | one dimension, any length |
| `i32[4]` | one dimension, exactly 4 |
| `i32[2,4]` | two rows of four |
| `i32[,4]` | any number of rows, each four wide |
| `i32[2,]` | two rows, any width |
| `i32[,]` | a matrix of any shape |
| `i32[2,2,3]` | three dimensions, all fixed |
| `i32[,2,]` | three dimensions, the middle one fixed |

An entry that gives a size fixes that dimension and the argument has to match it.  An entry left empty leaves the dimension open.  There is no limit on the number of dimensions, and `i32[]` is the one-dimensional case of the same rule rather than a special form.

Both the rank and each fixed extent are checked at the call:

```
fn corner(m : i32[2,4]) → i32:
    m[0, 0]

corner((3, 4) ⍴ (1…12))    // error: expected i32[2,4] (dimension 1 is 2), got a 3×4 array
corner([1, 2, 3, 4, 5, 6, 7, 8])   // error: expected i32[2,4] (2 dimensions), got array of length 8
```

A dimension is checked where it is written, so a type may fix some dimensions and leave others open:

```
fn rows_of_four(m : i32[,4]) → i32:
    m.shape[0]

rows_of_four((2, 4) ⍴ (1…8))     // 2
rows_of_four((3, 4) ⍴ (1…12))    // 3
rows_of_four((2, 3) ⍴ (1…6))     // error: dimension 2 is 4, got a 2×3 array
```

##### Reading the Open Dimensions

`.shape` is one extent per dimension, which is how a function reads what its own type left open:

```
fn sum_matrix(m : i32[,]) → i32:
    let t : mut = 0
    foreach r := 0…(m.shape[0] - 1):
        foreach c := 0…(m.shape[1] - 1):
            t ← t + m[r, c]
    t
```

`m.shape.sizeof` is the rank, and `v.shape[0]` is `v.sizeof` for a one-dimensional array.  A slice reports the shape it was cut to rather than the one it came from, so `sum_matrix(m[0…1])` sees two rows.

##### Writing a Matrix Out

Nested brackets give the elements a row at a time, one level of nesting per dimension:

```
let m := [[1, 2, 3], [4, 5, 6]]                    // 2×3
let c := [[[1, 2], [3, 4]], [[5, 6], [7, 8]]]      // 2×2×2
```

Such a literal is an argument like any other and meets the same checks:

```
corner([[1, 2, 3, 4], [5, 6, 7, 8]])   // fits i32[2,4]
corner([[1, 2, 3], [4, 5, 6]])         // error: dimension 2 is 4, got a 2×3 array
```

An empty entry is one extent the type does not name, not the absence of one.  Rows of differing lengths are therefore not a dimension at all, and such an array fits no matrix type, not even a wholly open one:

```
sum_matrix([[1, 2, 3], [4, 5]])

error: expected i32[,] (dimension 2 is one extent), got a 2×? array
whose rows differ in length
```

`?` is how a shape reports a dimension that has no single extent.

##### Elsewhere a Type Is Written

The same syntax spells a variable's type, a type alias, and a struct field.  A variable annotation checks the initializer's shape, and a scalar initializer fills every element as it does for one dimension:

```
let m : i32[2,3] = [[1, 2, 3], [4, 5, 6]]   // checked
let z : i32[2,3] = 0                        // 2×3 of zeros
let bad : i32[2,3] = (3, 2) ⍴ (1…6)        // error: declared 2×3, got 3×2

type Grid = i32[2,3]
```

An empty extent here takes the one the initializer had, while the extents that are written are still checked against it:

```
let b : i32[,3] = [[1, 2, 3], [4, 5, 6]]    // two rows, checked three wide
let b : i32[,3] = [[1, 2], [3, 4]]          // error: declared ?×3, got 2×2
```

A fill value has no extent to give, so it cannot stand in for one that was left empty:

```
let z : i32[,3] = 0

error: declared ?×3, but a fill value gives no extent for the empty dimension
```

Under `@repr(C)` a multi-dimensional field lays out as C's `T[n][m]`: the rows sit one after another, so `i32[2,3]` is 24 bytes and the alignment is still the element's.  Every dimension has to be fixed, since a dynamic one has no C representation.

#### Comparison with Other Languages

| Operation | C++ `vector` | Rust `Vec` | Python `list` | Go slice | NGPL |
|-----------|-------------|-----------|--------------|----------|---------------|
| Append | `push_back` | `push` | `append` | `append(s, v)` | `push` |
| Remove last | `pop_back` (returns nothing) | `pop` → `Option` | `pop()` raises | manual reslice | `pop` → `T?` |
| Insert at index | `insert` (iterator) | `insert` | `insert` | manual | `insert` |
| Remove at index | `erase` (iterator) | `remove` | `pop(i)` | manual | `remove` |
| Checked read | `at` throws | `get` → `Option` | none | none | `get` → `T?` |
| Unchecked read | `[]` | `[]` | `[]` | `[]` | `[]` |

The naming follows Rust rather than C++, whose `push_back`/`pop_back` carry a symmetry with `push_front` that no other language here needs, and whose `pop_back` returns nothing so that a caller must read before popping.  Python's `pop` raises on an empty list, which turns the common drain loop into either a length test or an exception handler; the optional makes it one expression.


### Iterators

A container hands out an iterator with `iterate()`.  The iterator has exactly one member function:

| Function | Result | Description |
|----------|--------|-------------|
| `next()` | `T?` | The next value, or `∅` when there are none left |

```
let it : mut = values.iterate()
let e : mut = it.next()
while e:
    use(e)
    e ← it.next()
```

The result is used directly as the condition; there is no need to compare it with `∅`.  See [Optionals in a Boolean Context](#optionals-in-a-boolean-context) for why an element of `0` does not end the loop.

That is the whole protocol.  An iterator is anything that can answer `next()`, which keeps the concept small enough that a container can provide one without implementing a trait, and keeps a consumer working for any container that does.

An iterator holds its own position, so several over the same container advance independently.  It reads the container as it is at the time of the call rather than taking a snapshot: a write to an element the iterator has not reached yet is seen when it gets there.

#### Arrays

```
let v : mut = [10, 20, 30]
let it : mut = v.iterate()
it.next()        // 10
it.next()        // 20
it.next()        // 30
it.next()        // ∅
```

Once exhausted an iterator stays exhausted; further calls keep answering `∅`.

#### Directories

`std.fs.cwd()` and any other directory can be iterated too.  Here the values are entries rather than plain elements:

```
let dir : mut = std.fs.cwd()
let it : mut = dir.iterate()
let e : mut = it.next()
while e:
    std.print(e.name, " ", e.type)
    e ← it.next()
```

| Member | Type | Description |
|--------|------|-------------|
| `name` | `str` | The entry's name within its directory, never a path |
| `type` | `std.filetype` | What kind of thing the entry is |

Entries arrive from the kernel in blocks, and the iterator refills its buffer as it empties rather than reading the whole directory up front — a directory can be far larger than the program wants to hold at once.

`.` and `..` are not produced.  Every caller that walks a tree would otherwise have to filter them, and one that forgets recurses for ever; leaving them out removes a whole class of bug at the cost of a fact the program almost certainly knows already.

The iterator reads through the directory's descriptor, so it stops working once that directory is closed or its scope ends.

#### File Types

`std.filetype` names the kinds of thing a directory entry can be, with the values of the `S_IF*` constants in `<sys/stat.h>`:

| Member | Value | `<sys/stat.h>` |
|--------|-------|----------------|
| `fifo` | 0x1000 | `S_IFIFO` |
| `chr` | 0x2000 | `S_IFCHR` |
| `dir` | 0x4000 | `S_IFDIR` |
| `blk` | 0x6000 | `S_IFBLK` |
| `reg` | 0x8000 | `S_IFREG` |
| `lnk` | 0xA000 | `S_IFLNK` |
| `sock` | 0xC000 | `S_IFSOCK` |
| `unknown` | 0 | none |

```
if e.type == std.filetype.dir:
    descend(e.name)
```

The kernel reports an entry's type as a `DT_*` value, which is the matching `S_IF*` value shifted right by twelve.  The `S_IF*` form is the one exposed, because it is what a program comparing against a `stat` result already has.

`unknown` has no `S_IF*` counterpart.  Some filesystems do not record an entry's kind in the directory itself, and report `DT_UNKNOWN`; an entry of that type has to be opened to find out what it is.  A program that must know the kind has to handle this rather than assume it never happens.

#### Values That Are Themselves Empty

An iterator marks a produced value as present, so an element that is itself `∅` is not mistaken for the end:

```
let v : mut = [∅, 1]
```

iterates twice.  This is the same mechanism that makes an element of `0` a value rather than a terminator, described below.

#### Comparison with Other Languages

| Language | Obtain | Advance | End signalled by |
|----------|--------|---------|------------------|
| C++ | `begin()` | `++it` | comparison with `end()` |
| Rust | `iter()` | `next()` | `None` |
| Python | `iter()` | `__next__` | `StopIteration` |
| Go | `range` | built into the loop | second return value |
| Zig | `iterator()` | `next()` | `null` |
| NGPL | `iterate()` | `next()` | `∅` |

Rust and Zig arrive at the same shape as this, and for the same reason: an end signalled by the return value needs no second call to test for it, no sentinel object to compare against, and no exception for a condition that is not exceptional.  C++'s pair of iterators is the outlier, and it is the one form where the two halves can be mismatched.


### Array Concatenation (`⧺`)

The `⧺` operator (U+29FA, DOUBLE PLUS) concatenates two arrays at the outermost dimension.

#### Syntax

```
left ⧺ right
```

Both operands must be arrays.  The result is a new array whose elements are all elements of `left` followed by all elements of `right`.

#### Precedence

`⧺` binds tighter than `+` but looser than `⍴`:

```
a + b ⧺ c         // a + (b ⧺ c)
generate(f, r) ⧺ 48 ⍴ [0]   // generate(f, r) ⧺ (48 ⍴ [0])
```

This allows `⧺` and `⍴` to combine naturally without parentheses for common patterns like building a partially initialized array.

#### Semantics

- Both operands must be arrays; a non-array operand is a type error.
- The result preserves the element type of the left operand (falling back to the right if the left has no explicit type).
- Concatenation with an empty array is the identity: `a ⧺ (0 ⍴ [0])` yields `a`.
- `⧺` is left-associative: `a ⧺ b ⧺ c` is `(a ⧺ b) ⧺ c`.
- `⧺` is a line-continuation operator: an expression can break after it.

#### Example

```
// Build message schedule: 16 loaded words followed by 48 zero placeholders.
let W : mut = generate(load_word, 0…15) ⧺ 48 ⍴ [0]
```

This is clearer than the equivalent `64 ⍴ generate(load_word, 0…15)` because it does not rely on the cycling semantics of `⍴` to silently repeat data that will be overwritten.

#### Comparison with Other Languages

| Language | Concatenation Syntax |
|----------|---------------------|
| APL      | `,` (catenate)      |
| BQN      | `∾` (join)          |
| Haskell  | `++`                |
| Python   | `+` (overloaded)    |
| Rust     | `.extend()` / `[a, b].concat()` |
| NGPL | `⧺`           |

Using a dedicated glyph avoids overloading `+` (which is element-wise addition on arrays) and is visually distinct from arithmetic.


### Fold Operators (`⌿` and `⍀`)

The fold operators are binary operators that reduce a container to a single value by repeatedly applying a function.  Two variants are provided:

- **Left fold** `⌿` (U+233F, APL FUNCTIONAL SYMBOL SLASH BAR): processes elements left-to-right.
- **Right fold** `⍀` (U+2340, APL FUNCTIONAL SYMBOL BACKSLASH BAR): processes elements right-to-left.

#### Syntax

```
func ⌿ container
func ⌿ (container, init)
func ⍀ container
func ⍀ (container, init)
```

- **func** (left operand): a binary function (named function, lambda, or any callable).
- **container** (right operand): an array or range to fold over.
- When the right operand is a 2-tuple literal `(container, init)`, the second element provides the initial accumulator value.
- When the right operand is not a 2-tuple literal, no initial value is provided: the leftmost element (for `⌿`) or rightmost element (for `⍀`) of the container is used as the initial accumulator.  In this case the container must not be empty.

#### Precedence

`⌿` and `⍀` bind at the same level as `⍴` (tighter than arithmetic, looser than unary).  The right operand is parsed at range-expression level, so `f ⌿ 1…5` works without parentheses.  Both are line-continuation operators.

#### Semantics

**With initial value** (2-tuple right operand):

Left fold processes all elements, starting from the initial value:

```
f ⌿ ([a, b, c], init) = f(f(f(init, a), b), c)
```

Right fold processes all elements in reverse, starting from the initial value:

```
f ⍀ ([a, b, c], init) = f(a, f(b, f(c, init)))
```

When the container is empty, both folds return the initial value unchanged.

**Without initial value** (bare container):

Left fold uses the first element as the accumulator and folds over the remaining elements:

```
f ⌿ [a, b, c] = f(f(a, b), c)
```

Right fold uses the last element as the accumulator and folds over the remaining elements in reverse:

```
f ⍀ [a, b, c] = f(a, f(b, c))
```

Folding an empty container without an initial value is a runtime error.  A single-element container returns that element unchanged.

#### Examples

Summation without initial value:

```
let total : mut = (λa : int, b : int → int: a + b) ⌿ [1, 2, 3, 4, 5]
// total = 15
```

Summation with explicit initial value:

```
let total : mut = (λa : int, b : int → int: a + b) ⌿ ([1, 2, 3, 4, 5], 100)
// total = 115
```

Bit packing (used in SHA-256 to assemble the final hash from eight 32-bit words).  The initial value 0 is needed because the first hash word must be shifted into position:

```
let hash : mut = (λacc : int, h : int → int: (acc « 32) | h) ⌿ (H, 0)
```

String concatenation without initial value:

```
let joined : mut = (λacc : str, s : str → str: acc + s) ⌿ ["a", "b", "c"]
// joined = "abc"
```

Folding over a range:

```
let sum : mut = (λa : int, b : int → int: a + b) ⌿ 1…100
```

Named functions as the left operand:

```
fn add x : int, y : int → int:
    x + y

let total : mut = add ⌿ [10, 20, 30]   // 60
```

Currying and fold combine naturally.  A curried function produces the mapping, and fold reduces the result:

```
fn multiply a : int, b : int → int:
    a * b

let triple : mut = multiply(3)
let tripled : mut = generate(triple, 1…5)   // [3, 6, 9, 12, 15]
let total : mut = add ⌿ tripled             // 45
```

#### Design Rationale

| Feature | APL/BQN | Haskell | Rust | Python | NGPL |
|---------|---------|---------|------|--------|---------------|
| Left fold | `/` (reduce) | `foldl`/`foldl1` | `.fold()` | `functools.reduce` | `f ⌿ x` |
| Right fold | N/A | `foldr`/`foldr1` | `.rfold()` | N/A | `f ⍀ x` |
| Init value | optional | required/optional | required | optional | optional |
| Syntax | operator modifier | function | method | function | binary operator |

The glyph choice follows the APL tradition of using `/` and `\` with bar modifiers.  Using binary operator syntax (`func ⌿ container`) rather than function-call syntax aligns fold with other array operators in the language (`⍴`, `⧺`) and reads naturally: the function is on the left, the data on the right.

The initial value is optional.  When omitted, the first or last element of the container serves as the accumulator, matching the behavior of APL's reduce and Haskell's `foldl1`/`foldr1`.  When an initial value is needed (e.g., when the accumulator type differs from the element type, or when the container may be empty), a 2-tuple literal `(container, init)` on the right side provides it.  This avoids a separate operator or function for the two cases.

Both folds accept arrays and ranges as containers.  Using a non-iterable value (such as a scalar integer) is a type error.


### The `catch` Statement

The `catch` statement provides scoped error handling at the syntactic level.  Unlike exception systems in C++ or Java, `catch` blocks do **not** intercept errors from called functions.  Only errors that originate from operations directly written inside the `catch` block are caught.

#### Syntax

```
fn safe_access arr : i32[], idx ¤ptrdiff : i32 → i32?:
    catch:
        arr[idx]
```

The `catch` keyword is followed by a block (using `:` with indentation or `{ }`), following the same rules as `if`, `while`, and `foreach`.  The enclosing function must have an optional (`T?`) or expected (`T!`, i.e., `T?std.errors`) return type.

#### Semantics

When an operation inside the `catch` block raises a runtime error (such as an out-of-bounds array access, integer overflow, or type error):

1. The error does **not** terminate the program.
2. The error is converted to the appropriate return value:
   - For **optional** return types (`T?`): the function returns `∅`.
   - For **expected** return types (`T!`): the function returns `err(e)` where `e` is the corresponding `std.errors` enum value.
3. Execution resumes at the function's caller.

If no error occurs, the block's result value is used normally as the function's return value (wrapped in `some()` or `ok()` as appropriate).

#### Error Mapping

Runtime errors are mapped to `std.errors` enum values:

| Python Exception  | `std.errors` Value    |
|-------------------|-----------------------|
| `IndexError`      | `index_out_of_range`  |
| `OverflowError`   | `integer_overflow`    |
| `TypeError`       | `type_mismatch`       |

If no matching enum value is found, a string description of the error is used as the error value.

#### Syntactic Scope Only

The critical design property of `catch` is **syntactic scope**.  Errors from function calls inside the `catch` block are **not** caught:

```
fn risky → i32:
    let a : mut = [1]
    a[99]              // raises IndexError

fn caller → i32?:
    catch:
        risky()        // error from risky() propagates — NOT caught
        let a : mut = [1, 2]
        a[5]           // this error WOULD be caught (direct operation)
```

This means:
- `a[5]` inside the `catch` block is a direct operation.  Its `IndexError` is caught and converted to `∅`.
- `risky()` is a function call.  Errors from inside `risky` propagate normally, as if the `catch` block were not present.

This design avoids the problems of stack-unwinding exception systems: reasoning about control flow remains local, and functions cannot silently swallow errors from their callees.

#### Comparison with Other Languages

| Feature | C++ `try/catch` | Rust `?` | Zig `catch` | NGPL |
|---------|-----------------|----------|-------------|---------------|
| Scope | Stack-unwinding | Expression-level | Expression-level | Syntactic block |
| Cross-call | Catches all | Propagates | Propagates | Does not catch |
| Error type | Exception classes | `Result<T,E>` | `anyerror` | `std.errors` enum |
| Syntax | Block with type | Postfix operator | Binary operator | Block statement |

The `catch` statement is complementary to the `?` postfix operator: `?` propagates errors from expected values, while `catch` converts direct runtime errors into return values.


### Built-in Test System

Unit testing is built into the language, similar to Rust's `#[test]` attribute.  Functions are annotated with `@test` to mark them as test functions.  The annotation accepts an optional list of function names that the test covers.

#### Annotation Syntax

```
@test
fn test_something → ∅:
    ...

@test(sha256)
fn test_sha256_abc → ∅:
    ...

@test(encrypt, decrypt)
fn test_round_trip → ∅:
    ...
```

#### Startup Function and Exit Code

Exactly one function may be annotated with `@start` to designate it as the program entry point.  Alternatively, the `--start NAME` command-line flag selects a function by name, overriding any `@start` annotation in the source.  The named function must exist and take no parameters.  The return type of the startup function determines the process exit code:

- **`→ ∅`** (or no return type annotation): the process exits with code 0.
- **`→ u8`**: the return value is used directly as the exit code (0–255).
- **`→ i8`**: the return value is mapped to unsigned (e.g., −1 becomes 255) and used as the exit code.
- **Any other return type**: a warning is issued and the process exits with code 0.

```
@start
fn main → u8:
    if some_check_failed():
        return 1
    0                           // success
```

| Feature | C/C++ | Rust | Zig | Go | NGPL |
|---------|-------|------|-----|----|---------------|
| Entry point | `main` | `main` | `pub fn main` | `func main` | `@start fn name` |
| Exit code type | `int` | `()` / `ExitCode` | `u8` / `void` | implicit 0 | `u8` / `i8` / `∅` |
| Default exit | 0 | 0 | 0 | 0 | 0 |

#### Execution Semantics

Test functions are always run unless explicitly skipped.  Their execution order depends on whether they reference specific functions:

1. **Standalone tests** (`@test` without references) run at startup, before the `@start` function.  If any standalone test fails, the program terminates immediately.

2. **Referenced tests** (`@test(func_name)`) run once, automatically, on the first call to any of the referenced functions.  This follows `pthread_once` semantics: the test executes exactly once regardless of how many times the referenced function is called.  If a test references multiple functions, it runs on whichever is called first.

3. **Test mode** (`--test` flag) runs all tests — both standalone and referenced — without executing the `@start` function.  The interpreter reports results and exits with status 0 (all passed) or 1 (any failed).

4. **Skip mode** (`--skip-tests` flag) suppresses all test execution during normal program runs.  Both standalone tests and referenced tests are skipped; only the `@start` function executes.  This is useful for production runs where test overhead is undesirable.  The `--skip-tests` flag has no effect in `--test` mode.

#### Assertion Functions

Two built-in assertion functions are available in all scopes:

- `assert(condition)` — fails if the condition is `false` or zero.  An optional second argument provides a custom error message: `assert(x > 0, "x must be positive")`.

- `assert_eq(expected, actual)` — fails if the two values differ.  The error message displays both values for easy comparison.  Large integers (such as cryptographic hashes) are displayed in hexadecimal.

#### Compile-Time Assertions

Two compile-time assertion functions verify conditions using only constant expressions.  If any argument is not a compile-time constant (i.e., it references a variable), a compilation error is raised immediately:

- `static_assert(condition)` — fails at compile time if the condition is `false` or zero.  An optional second argument provides a custom error message: `static_assert(2 + 2 == 4)`, `static_assert(false, "unreachable")`.

- `static_assert_eq(expected, actual)` — fails at compile time if the two constant values differ: `static_assert_eq(120, 2 * 3 * 4 * 5)`.

Constant expressions include literals, arithmetic/logic operations on literals, unary operators, and array/tuple literals composed of constants.  References to variables — even `let` variables — are not compile-time constants for these purposes; use `assert` or `assert_eq` for those.

```
static_assert(true)                     /* OK */
static_assert_eq(10, 3 + 7)            /* OK */
static_assert_eq("hello", "hello")     /* OK */

let x : mut = 42
static_assert(x)                       /* ERROR: not a compile-time constant */
```

| Feature | C/C++ | Rust | Zig | NGPL |
|---------|-------|------|-----|---------------|
| Compile-time assert | `static_assert` | `const_assert!` (nightly) | `comptime` + assert | `static_assert` / `static_assert_eq` |

#### Type Introspection

Built-in introspection functions use the `@` prefix and return values that can be compared for equality.  All `@` operations are compile-time: their arguments must be compile-time constant expressions (literals, constant arithmetic, other `@` expressions) or compile-time variables (parameter pack names, `comptime foreach` loop variables).  Passing a runtime variable is an error — use the equivalent runtime operation (e.g., `.sizeof`) instead.

- `@typeof(expr)` — evaluates the expression and returns a `type` value representing its type.  The type name reflects the concrete type: `int`, `i32`, `u8`, `str`, `bool`, `\N{EMPTY SET}`, `array`, `tuple`, `fn`, `\N{GREEK SMALL LETTER LAMDA}`, or an enum name.

- `@resultof(func)` — looks up a named function and returns a `type` value for its declared return type.

- `@sizeof(expr)` — returns the number of elements in a container.  Works on array literals, tuple literals, string literals, and parameter packs.  Passing a non-container (e.g., an integer or boolean) is an error.  For runtime containers, use `.sizeof` instead.

  The result carries a unit: for `u8[]` (byte arrays) the unit is `byte`; for all other containers the unit is `ptrdiff`.  Because dimensionless arithmetic is allowed with unit-bearing values, the sizeof result can be used directly in index computations, loop bounds, and arithmetic without explicit unit stripping.

```
// .sizeof is the runtime equivalent — use on variables
let arr : mut = [10, 20, 30]
let sz : mut = arr.sizeof          // 3 ptrdiff
let last : mut = sz - 1            // 2 ptrdiff (dimensionless 1 adopts unit)

// @sizeof works on compile-time constants
static_assert_eq(@sizeof([1, 2, 3]), @sizeof("abc"))
```

`@sizeof` is particularly useful for parameter packs, which are compile-time entities:

```
fn process args… : T':
    let i : mut int = 0
    while i < @sizeof(args):
        i ← i + 1
```

Type and result-of values can be compared with `==` and used with `static_assert_eq`:

```
fn example → i32: 42

// compile-time type checks on literals
static_assert_eq(@typeof(42), @typeof(1 + 2))  // both are int
static_assert_eq(@typeof("a"), @typeof("b"))   // both are str
static_assert_eq(@resultof(example), @resultof(example))
```

- `@unitof(expr)` — returns the unit attached to a value as a `UnitOfValue`.  The argument must be a compile-time constant expression.  If the value has no unit (dimensionless), returns a dimensionless unit value.  Supports equality (`==`) and inequality (`!=`) comparison with other `@unitof` results and with standalone unit references (`¤meter`, `¤byte`, etc.).

  A standalone unit reference `¤unit` (without a preceding expression) produces a `UnitOfValue` for comparison purposes:

```
// @unitof on compile-time unit expressions
static_assert_eq(@unitof(5 ¤meter), ¤meter)
assert_true(@unitof(42) != ¤meter)            // dimensionless
assert_true(@unitof(100 ¤meter / (10 ¤second)) == ¤meter/second)
```

| Feature | C++ | Rust | Zig | NGPL |
|---------|-----|------|-----|---------------|
| Type-of expression | `decltype(expr)` | — | `@TypeOf` | `@typeof(expr)` |
| Return type query | `decltype(f())` | — | `@typeInfo` | `@resultof(func)` |
| Size query | `std::size(c)` | `c.len()` | `x.len` | `@sizeof(expr)` |
| Unit query | — | — | — | `@unitof(expr)` |
| Type equality | `std::is_same_v` | `TypeId` | `==` | `==` |

#### Test Output

In normal mode, only failing tests produce output — passing tests are silent.  All standalone tests run before aborting, so every failure is reported in one pass.  Referenced tests that fail during execution terminate the program immediately.

In `--test` mode, every test result is printed and a summary follows:
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
fn test_sha256_empty → ∅:
    let data : mut = std.bytes("")
    let hash : mut = sha256(data)
    assert_eq(hash, 0xe3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855)

@test(sha256)
fn test_sha256_abc → ∅:
    let data : mut = std.bytes("abc")
    let hash : mut = sha256(data)
    assert_eq(hash, 0xba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad)
```

#### Design Rationale

The test system draws from several languages:

| Feature | Rust | Zig | NGPL |
|---------|------|-----|---------------|
| Annotation | `#[test]` | `test` block | `@test` / `@test(func)` |
| Runs with program | No (`cargo test` only) | No | Yes (always, unless skipped) |
| Function-level binding | No | No | Yes (`@test(func)` triggers on first call) |
| Assertion | `assert!` macro | `std.testing.expect` | `assert` / `assert_eq` builtins |

The function-level binding via `@test(func)` is unique to NGPL.  It ensures that a function's tests run before the function is ever used in production, catching regressions at the earliest possible point.  The `pthread_once` execution model ensures no runtime overhead after the first call.

The `std.bytes(string)` function creates a `Bytes` object from a UTF-8 string literal, enabling test functions to construct known inputs for cryptographic and binary data operations.

### Expected Diagnostic Testing (`@expect`)

The `@expect` annotation allows writing tests that verify the interpreter/compiler produces specific error or warning messages.  This is essential for testing that the language's static and dynamic checks actually reject invalid programs and produce the correct diagnostics.

`@expect` can be applied at two levels: **function-level** (before a function definition) and **statement-level** (before an individual statement inside a function body).

#### Function-Level Syntax

```
@expect error "regex pattern"
@expect warning "regex pattern"
fn function_name → ∅:
    /* code that should trigger the diagnostic */
```

Multiple `@expect` annotations can appear before a single function.  The level keyword (`error` or `warning`) specifies what kind of diagnostic is expected, and the string is a regular expression matched against the actual diagnostic message.

#### Statement-Level Syntax

```
fn test_something → ∅:
    @expect warning "redefinition of foreach variable"
    let i : mut = 99
```

Statement-level `@expect` wraps a single statement.  The evaluator executes the statement, captures any errors and warnings it produces, and matches them against the expectations.  If all expectations are satisfied, execution continues normally.  If any expectation is unmatched, the test fails.

This form is especially useful for testing warnings, since warnings do not terminate execution and the function can verify the behavior that follows the warning.

#### Semantics

**Function-level:**

1. The interpreter attempts to parse and evaluate the annotated function body.
2. Any error produced during parsing or evaluation is captured rather than terminating the interpreter.
3. Each captured diagnostic is matched against the `@expect` annotations in order.  An annotation is satisfied when its level matches and its regex pattern matches (via `re.search`) the diagnostic message.
4. If all `@expect` annotations are satisfied, the function is silently accepted — the test passes.
5. If any `@expect` annotations remain unmatched, the test fails with a diagnostic showing both the unmatched expectations and the actual diagnostics produced.
6. If no diagnostic is produced but one was expected, the test fails with "expected diagnostics not produced".

Since the interpreter stops at the first error in a function body, each `@expect error` function typically tests exactly one error condition.

**Statement-level:**

1. The evaluator executes the annotated statement, capturing any raised exceptions as errors and any warnings emitted during execution.
2. The captured diagnostics are matched against the expectations using the same regex-matching rules as function-level `@expect`.
3. If all expectations match, execution continues with the next statement.
4. If any expectation remains unmatched, a `TypeError` is raised (which the enclosing `@test` function will report as a test failure).

#### Error Recovery

When an `@expect`-annotated function has a parse error, the parser recovers by skipping tokens until the next top-level definition.  The parse error message is captured and matched against the expectations.  This allows testing for syntax errors without aborting the entire file.

#### Examples

Function-level `@expect` for errors:

```
@expect error "cannot assign to let binding 'x'"
fn error_let_assign() → ∅:
    let x := 42
    x ← 99

@expect error "unexpected token: 'fn'"
fn error_nested_fn() → ∅:
    fn inner() → ∅:
        std.print("bad")
```

Statement-level `@expect` for warnings inside a `@test` function:

```
@test
fn warn_foreach_redef → ∅:
    let total : mut = 0
    foreach i := 1…3:
        @expect warning "redefinition of foreach variable 'i'"
        let i : mut = 99
        total ← total + i
    assert_eq(total, 297)
```

This test verifies both that the warning is produced and that the redefined variable takes effect (each iteration uses 99, so the total is 297).

#### Integration with Test Modes

`@expect` tests are processed in both `--test` and normal mode:

- In `--test` mode, each function-level `@expect` function is reported like a regular test (`ok` / `FAILED`) and included in the test summary counts.  Statement-level `@expect` operates within the enclosing `@test` function.
- In normal mode, function-level `@expect` tests are verified silently on success.  If any `@expect` test fails, the program terminates with exit code 1 before running the `@start` function.
- The `--skip-tests` flag does **not** suppress function-level `@expect` verification — these are compile-time checks, not runtime tests.

#### Design Rationale

| Feature | Rust | LLVM FileCheck | NGPL |
|---------|------|----------------|---------------|
| Error testing | `#[should_panic]` | `// expected-error` | `@expect error "pattern"` |
| Warning testing | No | `// expected-warning` | `@expect warning "pattern"` |
| Pattern matching | No (message ignored) | Fixed substring | Regex |
| Parse error testing | No (compile error = test infra error) | Yes | Yes (parser recovers) |
| Statement granularity | No | Yes (line-based) | Yes (`@expect` on statements) |
| Integrated with test runner | Yes | Separate tool | Yes |

The `@expect` annotation fills a gap that most languages handle with external test harnesses.  By integrating diagnostic-expectation testing into the language's test system, the entire test suite — positive tests (`@test`) and negative tests (`@expect`) — can live in the same source files and run with the same `--test` invocation.  The statement-level form is particularly powerful: it allows testing warnings and non-fatal diagnostics within otherwise-normal test functions, verifying both the diagnostic and the runtime behavior that follows.


### Type Aliases

A type alias introduces a new name for an existing type.  The syntax mirrors variable and unit definitions:

```
type Index = i32
type Vec3 = f64[3]
type Row = i32[]
```

The alias can be used wherever a type name is accepted — variable definitions, function parameters, return types, and array element types:

```
type Offset = i32

fn advance(pos : Offset, delta : Offset) → Offset:
    pos + delta

let start : Offset = 0
```

#### Alias Chains

Aliases can refer to other aliases.  Resolution is transitive:

```
type Index = i32
type Offset = Index     // resolves to i32
```

Circular alias chains are detected and do not loop.

#### Interaction with Coercion

Type aliases are transparent to coercion.  A value of type `i32` is accepted where `Index` is expected and vice versa — the alias does not introduce a distinct type, only a name.

#### Design Rationale

Type aliases improve readability by attaching domain meaning to primitive types.  The syntax `type NAME = TYPE` is consistent with other top-level definitions (`unit NAME = formula`, `let NAME := expr`).

| Feature | Rust | C++ | Zig | NGPL |
|---------|------|-----|-----|------|
| Syntax | `type X = T` | `using X = T` | `const X = T` | `type X = T` |
| Distinct type | No (`type`), Yes (`struct`) | No | No | No |
| Transitive | Yes | Yes | Yes | Yes |


### Enumeration Types

Enumerations define a named set of integer constants grouped under a single type.  Enum members are not in the global namespace — they must be qualified with the enum's name (e.g., `Color.red`).

#### Syntax

```
enum Name [: underlying_type]:
    member1 [= value]
    member2 [= value]
    ...
```

The `enum` keyword introduces the definition.  An optional underlying type (e.g., `u8`, `u16`, `u32`) controls the storage width.  Each member is an identifier optionally followed by `= integer_value`.

#### Auto-Numbering

Members without explicit values are auto-numbered sequentially starting from 0 (or from the value after the previous explicitly-set member):

```
enum Color:
    red         /* 0 */
    green       /* 1 */
    blue        /* 2 */

enum Level:
    low         /* 0 */
    medium      /* 1 */
    high = 10   /* 10 */
    critical    /* 11 */
```

#### Member Access

Enum members are accessed through the enum's name, not as bare identifiers:

```
let c : mut = Color.red
let l : mut = Level.high
```

#### Comparison

Enum values of the same type can be compared with `==` and `!=`.  Comparing values from different enum types is a type error.  Enum values can also be compared with integer literals:

```
let c : mut = Color.red
assert_eq(c == Color.red, true)     /* same-type comparison */
assert_eq(c == 0, true)             /* compare with integer */
```

```
/* ERROR: cannot compare enum 'Color' with enum 'Status' */
let x : mut = Color.red == Status.ok
```

#### Underlying Type

The optional underlying type controls the integer width used to store enum values:

```
enum SmallEnum : u8:
    a
    b
    c
```

When no underlying type is specified, the default is `int` (arbitrary precision).

#### Flag Enums (`@flag`)

The `@flag` attribute changes auto-numbering to powers of two, making the enum suitable for bitwise flag combination:

```
@flag
enum Perms:
    read        /* 1 */
    write       /* 2 */
    exec        /* 4 */
```

If no member has the value 0, a `nil` member is automatically added:

```
Perms.nil       /* 0 — auto-generated */
Perms.read      /* 1 */
Perms.write     /* 2 */
Perms.exec      /* 4 */
```

If a member explicitly defines the value 0, no `nil` is generated:

```
@flag
enum Mode:
    off = 0     /* explicit zero — no auto nil */
    read = 1
    write = 2
```

#### Flag Operations

Flag enums support bitwise operations to combine, test, and remove flags:

| Operation | Syntax | Result |
|-----------|--------|--------|
| Combine | `a \| b` | union of flags |
| Intersect | `a & b` | intersection of flags |
| Toggle | `a ^ b` | symmetric difference |
| Complement | `~a` | all defined flags except those in `a` |

These operations are only valid on `@flag` enums.  Attempting bitwise operations on a non-flag enum is a type error.  Cross-enum operations (mixing two different enum types) are also type errors.

```
let rw : mut = Perms.read | Perms.write    /* combine: 3 */
let r : mut = rw & Perms.read              /* intersect: Perms.read */
let toggled : mut = rw ^ Perms.write       /* toggle: Perms.read */
let others : mut = ~rw                     /* complement: Perms.exec */

/* Test membership */
let has_read : mut = (rw & Perms.read) == Perms.read    /* true */
let has_exec : mut = (rw & Perms.exec) == Perms.exec    /* false */
```

The complement operator `~` masks against the union of all defined member values, so `~Perms.read` yields `Perms.write | Perms.exec` rather than a full integer complement.

#### The `std.errors` Enum

A built-in enum `std.errors` provides standardized error codes grouped by category:

| Range | Category | Members |
|-------|----------|---------|
| 100-199 | Runtime errors | `division_by_zero` (100), `index_out_of_range` (101), `stack_overflow` (102), `null_dereference` (103), `integer_overflow` (104), `assertion_failed` (105) |
| 200-299 | Compile-time errors | `type_mismatch` (200), `unknown_type` (201), `syntax_error` (202), `undefined_variable` (203), `arity_mismatch` (204) |
| 300-399 | Library/runtime errors | `file_not_found` (300), `permission_denied` (301), `io_error` (302), `allocation_failed` (303), `invalid_argument` (304) |

```
let err : mut = std.errors.division_by_zero
assert_eq(err == 100, true)
```

The grouping by integer ranges allows category checks:  runtime errors are in 100-199, compile-time errors in 200-299, library errors in 300-399.

#### Design Rationale

| Feature | C/C++ | Rust | Zig | NGPL |
|---------|-------|------|-----|---------------|
| Scoping | global (C), scoped (`enum class`, C++) | scoped | scoped | scoped (qualified access) |
| Underlying type | optional (`enum class : u8`) | implicit | `u8`..`u64` | optional (`: u8`) |
| Flag support | manual | `bitflags!` crate | manual | `@flag` attribute |
| Auto nil | N/A | N/A | N/A | auto-generated for `@flag` |
| Bitwise ops on flags | manual | `bitflags!` | manual | built-in (`\|`, `&`, `^`, `~`) |
| Cross-type comparison | allowed | error | error | error |

The `@flag` attribute eliminates the boilerplate of manually assigning powers of two and defining bitwise operations.  The automatic `nil` member for zero-valued flag sets prevents the common bug of forgetting to define an "empty" state.  Scoped access prevents name collisions between members of different enums.


### Generic Functions

Generic functions allow a single function definition to operate on multiple types.  A generic type parameter is any identifier immediately followed by an apostrophe (`'`), such as `T'`, `Elem'`, or `A'`.  The same generic name can appear in multiple parameters and in the return type.

#### Syntax

```
fn identity x : T' → T':
    x

fn add_g a : T', b : T' → T':
    a + b

fn pick_first a : T', b : U' → T':
    a
```

A function is generic when at least one parameter type or the return type contains a generic type parameter.  Generic type parameters are not declared separately — they are recognized by the trailing apostrophe in the type position.

#### Type Resolution

When a generic function is called, the interpreter resolves each generic type parameter from the actual arguments:

1. For each parameter with a generic type, the concrete type is determined from the runtime type of the corresponding argument.
2. If the same generic name appears in multiple parameters, all corresponding arguments must have the same type.  A mismatch raises a type error.
3. Once all generic parameters are resolved, the concrete types are substituted into all parameter types and the return type before coercion and execution proceed.

```
identity(42)         /* T' resolves to int */
identity(true)       /* T' resolves to bool */

let x : mut i32 = 7
identity(x)          /* T' resolves to i32 */

add_g(10, 20)        /* T' resolves to int, returns int */

let a : mut i32 = 1
let b : mut u32 = 2
add_g(a, b)          /* error: T' is i32 from 'a' but u32 from 'b' */
```

#### Return Type

If the return type uses a generic name that also appears in a parameter, the return type is determined by the parameter resolution.  If the return type uses a generic name that does not appear in any parameter, the first return statement determines the type.

#### Generic Arrays

Generic types compose with array and optional suffixes:

```
fn first_elem arr : T'[] → T':
    arr[0]
```

Here `T'[]` matches an array argument; `T'` resolves to the element type.

#### Currying

Generic functions support currying.  Partial application fixes some arguments and their types; the remaining generic parameters are resolved when the curried function is called:

```
let add10 : mut = add_g(10)    /* partial: T' not yet resolved */
add10(20)                 /* T' resolves to int, returns 30 */
```

#### Comparison with Other Languages

| Feature | Haskell | Rust | C++ | Zig | NGPL |
|---------|---------|------|-----|-----|---------------|
| Syntax | `a` (lowercase) | `<T>` | `template<typename T>` | `anytype` | `T'` (apostrophe suffix) |
| Declaration | implicit | explicit `<T>` block | explicit `template` | implicit | implicit (recognized by `'`) |
| Constraints | type classes | trait bounds | concepts (C++20) | comptime checks | resolved at call site |
| Monomorphization | no (dictionary passing) | yes | yes | yes | no (dynamic dispatch) |

The apostrophe-suffix convention keeps generic types visually distinct from concrete types without requiring a separate declaration block.  Unlike Rust's `<T>` or C++'s `template<typename T>`, no angle brackets or separate generic parameter list is needed — the generic is declared implicitly by its first use in the parameter list.


### Parameter Packs

Parameter packs allow functions to accept a variable number of arguments.  The last parameter of a function can be declared as a pack by appending the ellipsis `…` to the parameter name.  At the call site, all arguments beyond the regular parameters are captured into the pack.

#### Syntax

A pack parameter is declared by suffixing `…` to the parameter name.  An optional type annotation constrains all captured elements:

```
fn sum_all acc : int, rest… : int → int:
    let i : mut int = 0
    let s : mut = acc
    while i < rest.sizeof:
        s ← s + rest[i]
        i ← i + 1
    s

fn count_args args… → int:
    args.sizeof
```

When no type is given, the pack accepts arguments of any type.  When a concrete type is given, each captured argument is coerced to that type.

#### Pack Access

Inside the function body, the pack parameter behaves as a tuple:

- **Indexing**: `pack[i]` retrieves element `i` (zero-based).
- **Size**: `pack.sizeof` returns the number of captured elements (an `int`).
- **Type**: In a `comptime foreach`, `@typeof(v)` returns the type of the current element.

#### Generic Packs

A pack parameter can use a generic type.  In this case, each captured element retains its own type and no coercion is performed:

```
fn first_of args… : T':
    args[0]

first_of(42, "hello")    /* args[0] is int, args[1] is str */
```

When the pack type is generic, the generic is not resolved globally from pack elements — each element keeps its concrete type.  This differs from regular generic parameters where all positions sharing the same generic name must agree.

#### Empty Packs

A pack can capture zero arguments:

```
count_args()    /* returns 0 */
```

#### Currying

Currying applies to the regular (non-pack) parameters.  When a function with a pack receives fewer arguments than the number of regular parameters, it curries normally.  Once all regular parameters are supplied, additional arguments fill the pack:

```
fn greet prefix : str, names… : str → str:
    prefix

let g : mut = greet("Hello")    /* curries prefix */
g("Alice", "Bob")          /* names captures "Alice", "Bob" */
```

#### Comparison with Other Languages

| Feature | C++ | Rust | Zig | Python | NGPL |
|---------|-----|------|-----|--------|---------------|
| Syntax | `Args...` | none (macros) | `anytype` + comptime | `*args` | `name…` |
| Type constraint | `template<typename... Args>` | N/A | comptime checks | none | `: type` annotation |
| Access | fold expressions, `std::get<I>` | N/A | comptime for | `args[i]` | `name[i]` |
| Size | `sizeof...(Args)` | N/A | `args.len` | `len(args)` | `name.sizeof` |
| Heterogeneous | yes (each can differ) | N/A | yes | yes (untyped) | yes (with generic type) |

The ellipsis suffix keeps pack declarations compact.  Unlike C++ which requires template parameter packs and fold expressions, pack elements are accessed with ordinary subscript syntax and the `.sizeof` property.


### Comptime Foreach

`comptime foreach` extends the regular `foreach` loop to iterate over parameter packs and tuples.  Because pack elements can have different types, the loop variable takes on a different type in each iteration — the body is conceptually unrolled once per element.

#### Syntax

```
comptime foreach v := pack_or_container:
    /* body — v has a different type each iteration */
```

The syntax is identical to `foreach` except for the `comptime` prefix.

#### Iterating Over Parameter Packs

A regular `foreach` cannot iterate over a parameter pack because packs are heterogeneous tuples, not arrays.  `comptime foreach` resolves this:

```
fn ct_sum args… : int → int:
    let s : mut int = 0
    comptime foreach v := args:
        s ← s + v
    s

ct_sum(1, 2, 3, 4)    /* returns 10 */
```

Each iteration binds `v` to one pack element.  When the pack has a generic type, each element can have a different concrete type:

```
fn hetero_count args… → int:
    let ints : mut int = 0
    comptime foreach v := args:
        if @typeof(v) == @typeof(0):
            ints ← ints + 1
    ints

hetero_count(1, "a", 2)    /* returns 2 */
```

#### With enumerate

`enumerate` works inside `comptime foreach` to provide `(index, value)` pairs:

```
fn indexed_sum args… : int → int:
    let s : mut int = 0
    comptime foreach pair := enumerate(args):
        let idx : mut = pair[0]
        let val : mut = pair[1]
        s ← s + val * (idx + 1)
    s
```

#### Regular Containers

`comptime foreach` also works on arrays and ranges, behaving identically to `foreach` in those cases:

```
let s : mut int = 0
comptime foreach v := [10, 20, 30]:
    s ← s + v
/* s is 60 */
```

#### Comparison with Other Languages

| Feature | C++ | Rust | Zig | NGPL |
|---------|-----|------|-----|---------------|
| Pack iteration | fold expressions, `std::apply` | proc macros | `inline for` | `comptime foreach` |
| Heterogeneous | yes (each expansion differs) | N/A | yes (`inline for`) | yes (type changes per iteration) |
| Works on arrays | `std::apply` on tuples | `for` | `for` / `inline for` | yes (same as `foreach`) |

The `comptime foreach` keyword mirrors Zig's `inline for`, which also unrolls iterations at compile time to handle heterogeneous containers.  Unlike C++ fold expressions, the loop body uses ordinary imperative syntax — no special operator syntax is required.


### Standard Library: String Formatting

The `std.format` function creates formatted strings using replacement fields in the style of C++ `std::format`.

#### Signature

```
std.format(allocator, fmt_str, args…)
```

- **allocator**: an allocator instance (from `std.arena.allocator()` or `std.heap.allocator()`) used to back the returned string's memory.
- **fmt_str**: a format string containing literal text and `{}` replacement fields.
- **args**: a parameter pack of values to substitute into the replacement fields, consumed left to right.

#### Replacement Fields

Each `{}` in the format string consumes the next argument from the pack.  An optional format specifier follows a colon inside the braces:

| Specifier | Meaning | Example |
|-----------|---------|---------|
| (none) | Default formatting | `std.format(a, "{}", 42)` → `"42"` |
| `d` | Decimal integer | `std.format(a, "{:d}", 42)` → `"42"` |
| `x` | Lowercase hexadecimal | `std.format(a, "{:x}", 255)` → `"ff"` |
| `X` | Uppercase hexadecimal | `std.format(a, "{:X}", 255)` → `"FF"` |
| `b` | Binary | `std.format(a, "{:b}", 10)` → `"1010"` |
| `o` | Octal | `std.format(a, "{:o}", 8)` → `"10"` |
| `c` | Character (from code point) | `std.format(a, "{:c}", 65)` → `"A"` |

Literal braces are escaped by doubling: `{{` produces `{`, `}}` produces `}`.

#### Type Formatting

Each value type has a default representation:

- **Integers**: decimal digits (or the specified base with a format specifier).
- **Strings**: the string content (no quotes).
- **Booleans**: `true` or `false`.
- **Arrays/vectors**: elements enclosed in `[` and `]`, comma-separated.  Nested arrays produce nested brackets: `[[1, 2], [3, 4]]`.
- **Tuples**: same bracket notation as arrays.
- **Enums**: the enum member name prefixed by the type name.
- **None**: `∅`.
- **Types**: the type name.

```
let alloc : mut = std.arena.allocator()

std.format(alloc, "{} + {} = {}", 1, 2, 3)       /* "1 + 2 = 3" */
std.format(alloc, "hex: {:x}", 255)               /* "hex: ff" */
std.format(alloc, "arr: {}", [10, 20, 30])        /* "arr: [10, 20, 30]" */
std.format(alloc, "{{{}}}", "x")                  /* "{x}" */

alloc.deinit()
```

#### Comparison with Other Languages

| Feature | C++ `std::format` | Python `format` | Rust `format!` | NGPL |
|---------|-------------------|-----------------|----------------|---------------|
| Syntax | `"{}"` | `"{}"` | `"{}"` | `"{}"` |
| Positional args | `"{0}"` | `"{0}"` | `"{0}"` | sequential only |
| Named args | no | `"{name}"` | named in macro | no |
| Format spec | `"{:x}"` | `"{:x}"` | `"{:x}"` | `"{:x}"` |
| Allocator | no | no | no | first argument |
| Type-safe | compile-time | runtime | compile-time | runtime |

The allocator parameter ensures that the caller controls where the formatted string is allocated, following the language's principle of explicit memory management.  Unlike C++ `std::format` which allocates via `std::allocator`, the allocator is a visible first-class argument.


### Resource Lifetime and Scope

A value that holds an operating system resource — an open file or directory, so far — is owned by the binding it was assigned to.  When that binding's scope ends, the resource is released:

```
@start
fn main() → ∅:
    let dir : mut = std.fs.cwd()
    let file : mut = dir.open_file("data.bin")
    let data : mut = file.read_file(alloc)
    std.print(data.sizeof)
    // main's scope ends here: file is closed, then dir
```

Nothing in the source says to close the file.  The scope in which `file` was defined ends at the end of `main`, and that is enough to know the descriptor is finished with.

This is what a `defer` statement would express one call at a time, without needing the statement: the release is attached to the binding rather than written out at the point of acquisition, so it cannot be forgotten, cannot be written twice, and does not have to be repeated on every path out of the function.

#### Order

Bindings are destroyed in reverse order of definition.  A resource acquired by using an earlier one is therefore released before the thing it came from — above, `file` is closed before `dir`, never the other way round.

#### Every Exit

The scope ends however it is left: by running off the end, by an early `return`, or by an error propagating out.  A file opened before a failing operation is closed while that error travels outward.

A destructor that fails does not replace the reason the scope was left.  The failure is reported as a warning, and the original return or error continues on its way — a program that is already failing should not have its diagnosis replaced by a complaint about the cleanup.

#### Ownership

Two kinds of binding are not destroyed by the scope that names them.

**Returned values.**  Ownership passes to the caller, so a function may open a file and hand it back:

```
fn open_input():
    let dir : mut = std.fs.cwd()
    dir.open_file("input.txt")
```

`dir` is closed as `open_input` returns; the file is not, because it is the value being handed over.  It is then owned by whatever binding receives it, and closed when *that* scope ends.

**Parameters.**  An argument names a value the caller owns, so a function that takes a file does not close it:

```
fn read_all(f, alloc):
    f.read_file(alloc)
```

The caller's file is still open after `read_all` returns.

#### Releasing Early

`close()` releases the resource before the scope ends, for a program that knows it is finished sooner:

```
let file : mut = dir.open_file("data.bin")
let data : mut = file.read_file(alloc)
file.close()
process_for_a_long_time(data)
```

Once closed, the value is unavailable.  Every operation on it is an error:

```
file.close()
_ ← file.fd

error: fd: file is closed
```

That is the point of making close destructive rather than a hint.  A file descriptor number is reused by the kernel as soon as it is released, so an operation on a closed file would not fail — it would silently act on whatever unrelated file has since been given the same number.

Closing twice is an error for the same reason:

```
error: close: file is closed
```

The second `close` says the program has lost track of the descriptor's lifetime.  Scope-end release is not an error after an explicit `close`, however: the program said it was finished early, and the scope ending afterwards has nothing left to do.

#### Temporaries

A resource that is never assigned to anything has no binding to own it and no scope to end.  Such a temporary is released when the statement that produced it finishes:

```
let file : mut = std.fs.cwd().open_file("data.bin")
```

The directory exists only to reach the file.  Its descriptor is released as the statement ends, while the file it produced lives on in `file` and is released when *that* binding's scope ends.  Writing the directory into a binding of its own would instead hold it open for the whole scope, which is the reason to prefer the form above when the directory is not needed again.

The release is observable, because descriptors are handed out lowest-first:

```
let file : mut = std.fs.cwd().open_file("data.bin")   // directory 4, file 5
let later : mut = std.fs.cwd()                        // 4 again
```

A statement keeps what it binds to a name and what it produces as its own value; everything else it made was needed only while it ran.

#### What Is Not Yet Tracked

Ownership is followed through bindings, returns, parameters, and temporaries.  It is not yet followed into the other places a value can be put — stored in a global, in a struct field, or in an array — where the resource is released when the defining scope ends even though something else still refers to it.

Nor is a resource released when the binding holding it is overwritten:

```
foreach i := 1…50:
    let f : mut = std.fs.cwd().open_file("data.bin")
    use(f)
```

Each iteration rebinds `f`, and the file the previous iteration opened loses its only binding without being released; the descriptors accumulate until the function returns.  Releasing on reassignment is the rule that would close this, and it needs to know that nothing else refers to the old value — which is the ownership question again.

Closing these gaps is the business of the ownership and borrow system, which is a separate and larger piece of work.

#### Comparison with Other Languages

| Feature | C | C++ | Rust | Zig | Go | NGPL |
|---------|---|-----|------|-----|-----|---------------|
| Release at scope end | no | destructors | `Drop` | `defer` | `defer` (function) | automatic |
| Written at the acquisition | n/a | no | no | yes | yes | no |
| Ownership passes on return | n/a | yes (move) | yes | manual | manual | yes |
| Use after release | undefined | undefined | rejected at compile time | undefined | undefined | error at runtime |
| Double release | undefined | n/a | rejected at compile time | possible | possible | error |

The model is C++'s and Rust's rather than Go's and Zig's: the release belongs to the type, not to a statement the programmer has to remember at each acquisition.  `defer` is the alternative that was considered and not taken — it is explicit, but it puts the burden back on every use, and a `defer` that is forgotten looks exactly like code that never needed one.

Where this differs from C++ and Rust is what happens on a mistake.  Both make use-after-release undefined or impossible; here it is a diagnosed error at runtime.  A compile-time answer needs the ownership system that is still to come, and until then a definite error is better than an operation on whatever file inherited the descriptor number.


### Standard Library: Memory Allocators

The standard library provides two allocator subsystems under the `std` module: a global heap allocator and per-instance arena allocators.  Both return allocator objects with an `alloc(size)` method that yields a byte buffer.

#### Heap Allocator (`std.heap`)

```
let alloc : mut = std.heap.allocator()
let buf : mut = alloc.alloc(4096)
```

`std.heap.allocator()` returns the global mmap-backed allocator.  It uses a bump-pointer strategy within large (4 MiB minimum) anonymous mmap regions.  Individual allocations cannot be freed; the allocator is intended for long-lived program state.

#### Arena Allocator (`std.arena`)

```
let alloc : mut = std.arena.allocator()
let dir : mut = std.fs.cwd()
let file : mut = dir.open_file("data.bin")
let data : mut = file.read_file(alloc)
/* ... use data ... */
alloc.deinit()
```

`std.arena.allocator()` creates a new, independent arena allocator each time it is called.  Like the heap allocator, it uses mmap-backed bump allocation.  The key difference is the `deinit()` method: calling it releases all memory regions owned by the arena at once, without tracking individual allocations.

| Method | Description |
|--------|-------------|
| `alloc(size)` | Allocate `size` bytes from the arena; returns a byte buffer |
| `reset()` | Release all memory owned by this arena; the allocator remains usable for new allocations |
| `deinit()` | Release all memory and permanently disable the arena; further `alloc` calls raise an error |

Arenas are useful when a group of allocations share a common lifetime (e.g., processing a single request or computing a hash).  The pattern is: create an arena, perform all allocations from it, then `deinit()` when the work is complete.

#### Comparison

| Feature | `std.heap` | `std.arena` |
|---------|-----------|-------------|
| Instance | global singleton | per-call, independent |
| Individual free | no | no |
| Bulk free | no | `deinit()` releases all |
| Use case | long-lived program state | scoped, bounded-lifetime work |

Both allocators accept the same interface (`alloc(size)`) and can be passed interchangeably to functions like `file.read_file(allocator)`.


### Product Type Layout (`@repr`)

A struct has no defined layout unless it asks for one.  The implementation may order its fields as it likes and insert or omit padding as it likes, which leaves it free to sort fields by alignment and waste nothing:

```
struct Loose:
    a : u8
    b : i64
    c : u8
```

Nothing in the language reveals where `a`, `b`, and `c` sit in memory, and nothing may depend on it.  This is the right default: the layout that a source-order reading would give is rarely the layout a program wants, and freezing it by accident costs memory in every program that never needed the guarantee.

The freedom has to be given up when the bytes are the point — when a struct is handed to a foreign function, mapped over a file or a device register, or sent across a wire.  The `@repr` attribute does that:

```
@repr(C)
struct Point:
    x : i32
    y : i64
```

`@repr(C)` is currently the only layout defined.  An unrecognized name is rejected at parse time rather than ignored, since silently accepting `@repr(packed)` and laying the struct out some other way is the one behavior guaranteed to corrupt data.

#### The C Layout

`@repr(C)` produces exactly what a C compiler produces for the same declaration on the target, following the System V AMD64 psABI on x86-64:

* fields are placed in declaration order;
* each field begins at the next offset that is a multiple of its own alignment, and the bytes skipped become padding;
* the struct's alignment is the largest alignment among its fields;
* the struct's size is rounded up to a multiple of that alignment, so that every element of an array of the struct stays aligned.

For `Point` above, `x` occupies bytes 0–3, four bytes of padding follow, and `y` occupies bytes 8–15 — sixteen bytes with eight-byte alignment, matching `struct { int32_t x; int64_t y; }`.

An empty `@repr(C)` struct has size 0 and alignment 1, as in C.  (C++ would give it size 1 so that two objects have distinct addresses; the language imposes no such requirement.)

#### Querying the Layout

A struct with a defined layout answers three questions, on the type itself or on any instance of it.  All three results carry the `byte` unit:

| Query | Result | Description |
|-------|--------|-------------|
| `T.sizeof` | `int¤byte` | Size of the struct, including tail padding |
| `T.alignof` | `int¤byte` | Alignment of the struct |
| `T.offsetof(name)` | `int¤byte` | Offset of the named field from the start |

```
@repr(C)
struct Mixed:
    a : u8
    b : i32
    c : u8

Mixed.sizeof            // 12 B — three bytes of tail padding
Mixed.alignof           // 4 B
Mixed.offsetof("b")     // 4 B
```

Asking any of the three of a struct without `@repr(C)` is an error, not a guess:

```
Loose.sizeof
error: struct 'Loose' has no defined layout; annotate it with @repr(C) to give it one
```

This is the substantive difference the attribute makes.  A size that the implementation is free to change is not a size a program can use, so reporting one would invite exactly the dependency the default is designed to prevent.

#### Which Types May Appear

Every field of a `@repr(C)` struct must have a type with a C representation.  The rule is checked when the struct is defined, not when its layout is first requested, so the error appears where the offending field is written:

| Field type | Allowed | Reason |
|------------|---------|--------|
| `i8`…`i64`, `u8`…`u64`, `usize`, `byte`, `bool` | yes | fixed width |
| `f16`, `f32`, `f64`, `bfloat` | yes | fixed width |
| `i32fast` and other fast types | yes | width is platform-defined but concrete |
| `T[N]` | yes, if `T` is | contiguous, `N × sizeof(T)` bytes |
| another `@repr(C)` struct | yes | has a layout of its own |
| `int`, `float` | no | arbitrary precision, no fixed width |
| `str` | no | not a plain sequence of bytes |
| `T?`, `T?E` | no | representation is not defined |
| `T[]` | no | dynamically sized |
| a struct without `@repr(C)` | no | has no layout to embed |

```
@repr(C)
struct Header:
    magic : u32
    length : int

error: in @repr(C) struct 'Header', field 'length': type 'int' is
arbitrary-precision and has no defined C representation; use a sized
type such as i64
```

A struct that contains itself is rejected for the same reason a C struct cannot: the layout would have no finite size.

#### Interaction with the Rest of the Language

`@repr` constrains only layout.  A `@repr(C)` struct is an ordinary struct in every other respect: it takes methods through `impl`, its fields are read and assigned the same way, and it obeys the same move semantics.  Nor does the attribute imply anything about how the struct is passed to or returned from a function — argument passing is a separate question from in-memory layout, and the psABI answers it with separate rules.

In the interpreter the attribute has no effect on execution: values are Python objects, not byte buffers, so nothing observes the padding.  It is recorded and validated because the two consumers that will observe it — foreign function calls and the compiler's code generator — need it to have been checked at the point of definition rather than discovered to be impossible later.

#### Comparison with Other Languages

| Feature | C | C++ | Rust | Zig | NGPL |
|---------|---|-----|------|-----|---------------|
| Default layout | declaration order | declaration order | unspecified | unspecified | unspecified |
| Opt in to C layout | n/a (is the default) | n/a | `#[repr(C)]` | `extern struct` | `@repr(C)` |
| Field reordering allowed | no | no | yes (default) | yes (default) | yes (default) |
| Size of a layout-free struct | n/a | n/a | `size_of` still answers | `@sizeOf` still answers | error |
| Empty struct size | 0 | 1 | 0 | 0 | 0 |
| Packed variant | `__attribute__((packed))` | attribute | `#[repr(packed)]` | `packed struct` | not yet defined |

The attribute is Rust's `#[repr(C)]` under a different spelling, and the reasoning is the same: an unspecified default lets the implementation pack better, and an explicit opt-in serves the cases that need to match a foreign definition.

The one deliberate departure is that Rust and Zig will still tell a program the size of a layout-free struct, on the grounds that the number is true for the current compilation even if it is not stable across compilations.  Here that question is an error, because a number that is accurate today and different tomorrow is precisely the kind of fact a program should not be able to build on.

A packed layout — one that suppresses padding entirely — is a natural second `@repr` kind and is not yet defined.


### Standard Library: System Environment

Three submodules of `std` expose the context the operating system hands to a running program: `std.args` for the command line, `std.env` for the environment, and `std.sys` for the CPU and memory properties of the machine.  All three are read-only.  A program cannot rewrite its own command line or environment from the language; doing so is a property of the process that the runtime, not the program, is responsible for.

#### Command Line Parameters (`std.args`)

```
@start
fn main() → ∅:
    std.print("running as ", std.args.program())
    foreach arg := std.args.all():
        std.print("parameter: ", arg)
```

| Method | Result | Description |
|--------|--------|-------------|
| `program()` | `str` | The name the program was invoked as |
| `count()` | `int¤count` | Number of parameters, excluding the program name |
| `get(i)` | `str` | Parameter at zero-based index `i` |
| `all()` | `str[]` | All parameters, excluding the program name |

The program name is deliberately *not* the first element of `all()`.  Treating it as parameter zero is a C convention that forces every caller to remember an off-by-one adjustment; here `count()` and `all().sizeof` are the number of things the user actually typed after the program name.

`get(i)` raises an error when `i` is not less than `count()`.  It does not return an empty string or `∅` for an out-of-range index, because a missing parameter is a mistake in the program's own logic rather than a condition it should silently absorb.  Programs that do not know whether a parameter is present should compare against `count()` first, or iterate `all()`.

An empty parameter is preserved as an empty string and is distinct from an absent one.

When running under the interpreter, everything after a `--` separator on the interpreter's command line becomes the program's parameters:

```
$ python -m interp program.nl -- alpha "beta gamma" delta
```

The separator may be omitted when no parameter could be mistaken for an interpreter option.  A compiled program takes its command line directly from the initial process stack, and the `--` separator does not apply.

#### Process Environment (`std.env`)

```
let home : mut = std.env.get("HOME") ?? "/"
foreach name := std.env.names():
    std.print(name, " = ", std.env.get(name) ?? "")
```

| Method | Result | Description |
|--------|--------|-------------|
| `get(name)` | `str?` | Value of the variable, or `∅` when it is not set |
| `has(name)` | `bool` | Whether the variable is present |
| `count()` | `int¤count` | Number of variables in the environment |
| `names()` | `str[]` | Names of all variables |

`get` returns an optional rather than an empty string for an unset variable, because an environment variable set to the empty string is a meaningful and distinct state: `FOO=` is present with an empty value, while an unset `FOO` is absent.  Collapsing the two — as `getenv` in C does not, but as many convenience wrappers do — loses information that shell scripts routinely depend on.  The `??` operator supplies a default in the common case:

```
let verbose : mut = std.env.get("VERBOSE") ?? "0"
```

The environment is read on each call rather than snapshotted at startup, so a variable changed by a lower layer of the runtime is observed by the next call.

The operating system does not guarantee that environment variables are valid UTF-8, but the language requires that every `str` is.  Byte sequences that are not valid UTF-8 are therefore replaced with U+FFFD (REPLACEMENT CHARACTER) rather than raising an error, so that one malformed variable cannot make `names()` fail for the whole environment.

#### System Properties (`std.sys`)

```
let workers : mut = std.sys.usable_cpus()
std.print("using ", workers, " of ", std.sys.total_cpus())
```

| Method | Result | Description |
|--------|--------|-------------|
| `affinity()` | `int` | CPU affinity mask; bit *n* is set when CPU *n* is usable |
| `affinity_cpus()` | `int[]` | Ids of the CPUs in the affinity mask, ascending |
| `usable_cpus()` | `int¤count` | Number of CPUs this program may run on |
| `online_cpus()` | `int¤count` | Number of CPUs currently online |
| `total_cpus()` | `int¤count` | Number of CPUs the system is configured with |
| `page_size()` | `int¤byte` | Size of a memory page |
| `total_memory()` | `int¤byte` | Total physical memory installed |

`usable_cpus()` is the value a program should use to size a worker pool.  It is the population count of the affinity mask, so it respects `taskset`, cpusets, and container CPU restrictions.  `total_cpus()` and `online_cpus()` describe the machine, not the program's share of it: a program that sizes its gang concurrency by `total_cpus()` will oversubscribe whenever it runs under any CPU restriction.  The three are ordered:

```
std.sys.usable_cpus() <= std.sys.online_cpus() <= std.sys.total_cpus()
```

The affinity mask is an ordinary integer of arbitrary width, not a fixed 64-bit word, so it remains correct on systems with more than 64 CPUs.  `affinity_cpus()` converts the mask to the list of set CPU ids for programs that need to pin work to specific CPUs rather than merely count them.

Memory and page sizes carry the `byte` unit, so they combine correctly with `sizeof` results and other byte-valued quantities without further annotation:

```
let pages : mut = std.sys.total_memory() / std.sys.page_size()
```

#### Comparison with Other Languages

| Feature | C | Rust | Zig | Python | NGPL |
|---------|---|------|-----|--------|---------------|
| Command line | `argc`/`argv` params | `std::env::args()` | `std.process.args()` | `sys.argv` | `std.args` |
| Program name in list | yes (`argv[0]`) | yes (first item) | yes (first item) | yes (`argv[0]`) | no, separate `program()` |
| Unset variable | `NULL` | `Err`/`None` | error | `KeyError`/`None` | `∅` |
| Empty vs unset | distinct | distinct | distinct | distinct | distinct |
| Usable CPU count | `sched_getaffinity` | `available_parallelism()` | `getCpuCount()` | `len(sched_getaffinity(0))` | `std.sys.usable_cpus()` |
| Affinity mask exposed | yes (`cpu_set_t`) | no | no | as a set | yes, as an integer |
| Byte quantities typed | no | no | no | no | `¤byte` unit |

The design follows Rust and Zig in reporting an unset variable as an absence rather than a null pointer, and departs from all four in keeping the program name out of the parameter list and in attaching units to the byte- and count-valued results.


### Unit System

The language supports attaching physical units to numeric values.  Units enable compile-time and runtime dimensional analysis: addition requires matching dimensions, multiplication and division derive new dimensions, and assignment to a variable with a declared unit checks that the conversion is lossless for integers.

#### Syntax

A unit annotation uses `¤` followed by a unit name:

```
let distance ¤meter : mut = 100
let elapsed ¤second : mut = 10
let speed ¤meter/second : mut = distance / elapsed
```

The `¤` (U+00A4, CURRENCY SIGN) can appear in two positions:

1. **Variable definitions**: between the name and the colon/`:=`, declaring the variable's unit.
2. **Expressions** (postfix): after a primary expression, annotating the value with a unit.

Whitespace around `¤` is flexible: it can appear immediately after the preceding token (`x¤meter`, `42¤kilogram`) or separated by spaces (`x ¤ meter`).  This is a consequence of normal tokenization — `¤` is a single-character operator.

```
let d ¤kilometer : mut = 5     // variable with unit kilometer
d ← 3000¤meter           // expression with unit meter, converted to kilometer
```

#### Unit Names

Builtin units use identifier syntax with full names: `meter`, `second`, `kilogram`, `kilometer`, `millisecond`, `byte`, etc.  User-defined units are referenced with string syntax: `¤"speed"`, `¤"widgets"`.

Compound unit specifications combine names with `*` (multiplication), `/` (division), and `√` (square root):

```
let velocity ¤meter/second : mut = 10
let area ¤meter*meter : mut = 25
```

In expression context, `*` and `/` after `¤` are consumed as unit operators only when followed by another unit name, not by a number.  This avoids ambiguity with arithmetic operators:

```
let a ¤meter : mut = 5
let b : mut = a * 3            // 15 m (scalar multiplication, not unit formula)
```

#### Unit Definitions

New units are introduced with the `unit` keyword.  A base unit has no formula; a derived unit specifies the conversion in terms of existing units using integer ratios for exact representation:

```
unit mph = 1609344 / 3600000 * meter / second
unit widgets
```

User-defined units are referenced via strings (`¤"mph"`, `¤"widgets"`); the identifier form is reserved for builtin units.

#### Builtin Units

The interpreter provides the following builtin units:

**SI base**: `meter` (displayed as m), `second` (s), `kilogram` (kg), `ampere` (A), `kelvin` (K), `mole` (mol), `candela` (cd).

**SI derived (length)**: `kilometer` (km), `centimeter` (cm), `millimeter` (mm), `micrometer` (μm), `nanometer` (nm).

**SI derived (time)**: `millisecond` (ms), `microsecond` (μs), `nanosecond` (ns), `minute` (min), `hour` (h).

**SI derived (mass)**: `gram` (g), `milligram` (mg).

**SI derived (combined)**: `newton` (N), `pascal` (Pa), `joule` (J), `watt` (W), `hertz` (Hz), `volt` (V), `coulomb` (C).

**Byte units**: `byte` (displayed as B), `kilobyte` (kB), `kibibyte` (KiB), `megabyte` (MB), `mebibyte` (MiB), `gigabyte` (GB), `gibibyte` (GiB), `terabyte` (TB), `tebibyte` (TiB).

**Abstract**: `count`, `distance`, `ptrdiff`.

#### Dimensional Analysis Rules

- **Addition/subtraction**: both operands must have units with the same dimensions.  If the units differ (e.g., `km` and `m`), both are converted to their base form (factor = 1) before the operation.  If the units are identical, no conversion occurs.

- **Multiplication**: dimensions combine by adding exponents.  `meter * second` produces a unit with components `{meter: 1, second: 1}`.  Scalar multiplication (`5 * 3¤meter`) preserves the unit.

- **Division**: dimensions combine by subtracting exponents.  `meter / second` produces `{meter: 1, second: -1}`.  Division of identical units produces a dimensionless result (plain numeric value).

- **Comparison**: both operands must have the same dimensions.  Values are converted to base form before comparison.  One dimensionless operand is permitted (compared directly without unit checking).

- **Modulus**: same rules as addition (same dimensions required).  One dimensionless operand is permitted (result inherits the unit from the unit-bearing operand).

- **Dimensioned + dimensionless arithmetic**: when one operand carries a unit and the other is a plain (dimensionless) numeric value, the dimensionless value is treated as having a compatible, invisible unit.  This applies to addition, subtraction, multiplication, division, modulus, and comparisons.  For addition and subtraction the result inherits the unit.  For multiplication and division, scalar-times-unit and unit-times-scalar both preserve the unit; division of a dimensionless value by a unit-bearing value produces an inverse unit.  Modulus follows the same rule as addition (result inherits the unit).

  ```
  let a ¤meter : mut = 10
  let b : mut = a + 3       // 13 m
  let c : mut = 2 * a       // 20 m
  let d : mut = a / 5       // 2 m
  let e : mut = a % 3       // 1 m
  ```

  **Note**: assigning a plain dimensionless value to a variable with a declared unit is still an error.  The relaxation applies only to arithmetic operations, not to assignment or initialization.

#### Lossless Conversion

When assigning a value to a variable with a declared unit, the value must be convertible without loss.  For integer values, this means the converted result must be an exact integer:

```
let t ¤second : mut = 0
t ← 2000¤millisecond   // 2000 ms = 2 s (exact, allowed)
t ← 500¤millisecond    // 500 ms = 0.5 s (not integer, rejected)
```

Floating-point values convert without this restriction.

Conversion uses exact rational arithmetic (Python `fractions.Fraction`) internally, so precision is limited only by integer size, not by floating-point rounding.

#### Unit Inference

When a variable is defined with initialization but without an explicit unit, the unit is derived from the initialization value:

```
let a ¤meter : mut = 5
let b : mut = a              // b inherits unit m
let c : mut = b + a          // 10 m (works because b has unit m)
```

#### Unit Propagation through Ranges

When a `foreach` range has one or more unit-bearing bounds, the unit is propagated to the loop variable:

```
let total ¤byte : mut = 128
foreach off := 0…64…(total - 1):
    // off has unit byte, inherited from the range bound
    static_assert_eq(@unitof(off), ¤byte)
```

This allows sizeof results and other unit-bearing values to flow naturally through loop constructs without losing dimensional information.

#### Display

When formatting or printing a value with a unit, the unit's display name is appended after a space:

```
std.print(42¤meter)     // prints: 42 m
std.print(1024¤kibibyte) // prints: 1024 KiB
```

The builtin units use conventional abbreviations: `B` for byte, `m` for meter, `s` for second, etc.

#### Comparison with Other Languages

| Feature | Rust | C++ (proposed) | F# | NGPL |
|---------|------|----------------|-----|---------------|
| Units | third-party crate (`uom`) | no standard | units of measure | built-in |
| Syntax | type system | N/A | `[<Measure>]` attribute | `¤` annotation |
| Conversion | explicit | N/A | automatic | automatic with lossless check |
| Dimensional analysis | compile-time | N/A | compile-time | runtime |
| User-defined | via type aliases | N/A | custom measures | `unit` keyword |
| Lossless check | no | N/A | no | yes (integers) |

The `¤` syntax keeps unit annotations visually distinct from type annotations (which use `:`) and avoids ambiguity with function call or subscript delimiters.  The lossless conversion check for integers prevents silent truncation when converting between units of different scale.


Chapter 12: The Interpreter — The Interactive Read-Eval-Print Loop
------------------------------------------------------------------

### Entering the REPL

The interpreter starts an interactive session in three situations, in order of precedence:

1. `--repl` is given.  The source file, if any, is loaded first and its definitions become available, but the startup function is *not* run.
2. No source file is given at all.  The session starts with only `std` in scope.
3. A source file is given but defines no startup function.  Rather than exiting with nothing done, the interpreter hands the loaded definitions to the user.

```
$ ngpl                          # empty session
$ ngpl --repl program.nl        # load program.nl, do not run main
$ ngpl library.nl               # library.nl has no @start ⇒ REPL
```

The third case replaces what was previously a bare "nothing to execute" message.  A file of pure definitions is the normal shape of a library, and loading one interactively is the fastest way to exercise it.

Standalone tests still run before the session begins, so a session never starts on top of code already known to be broken.

`--test` requires a source file and never enters the REPL.

### What Can Be Entered

A source file may contain only definitions; every statement must live inside a function.  The REPL lifts that restriction, because the restriction exists to keep files reviewable, not to keep expressions from being evaluated.  An entry may be:

* any definition a file may contain — `fn`, `let`, `type`, `unit`, `enum`, `struct`, `impl`;
* any statement — assignment, `if`, `foreach`, `while`, `catch`;
* a bare expression, which is evaluated and its value shown.

```
>>> 1 + 2
3
>>> let x := 42
>>> x * 2
84
>>> foreach i := 1…3:
...     std.print(i)
...
1
2
3
```

Only a bare expression reports a value.  A statement that happens to end in an expression stays silent, exactly as it would inside a function body, so that a loop or a conditional does not print its last iteration's value.

Definitions accumulate in one environment for the life of the session: a function defined in one entry is callable from the next, and a function may refer to names defined earlier.

### Multi-Line Input

Input is read one line at a time and accumulated until it forms something complete.  Two rules decide when that is.

**A line that cannot stand alone continues.**  Input that stops in the middle of a bracket, a string literal, or an expression is incomplete, and the REPL reads on:

```
>>> 1 +
... 2
3
>>> std.print("a",
...           "b")
ab
```

**A layout block continues until an empty line.**  Once a line ending in `:` is followed by an indented body, input continues even though what has been typed would already parse:

```
>>> fn double(n : int) → int:
...     n * 2
...
>>> double(21)
42
```

The empty line is required because the alternative — ending the definition as soon as it parses — would make it impossible to give a function a second statement.  After `n * 2` the function is syntactically complete, so without the rule there would be no way to add a line to it.  This follows Python's REPL, and for the same reason.

An annotation on its own line is also incomplete, since the definition it applies to has not been given yet:

```
>>> @test
... fn test_double() → ∅:
...     assert_eq(double(21), 42)
...
test test_double ... ok
```

Because a `@test` function is run as soon as it is defined, the REPL is a direct way to develop a test: write it, watch it fail, fix the function, and define it again.

The empty line also serves as an escape.  Input that the rules above keep waiting on — a string literal accidentally left open, say — is abandoned by pressing Enter on an empty line, without having to guess what the interpreter is still waiting for.

`@expect`-annotated functions are accepted but not checked interactively; their expectations are verified when the file is run.

### Displaying Values

A result is shown using the language's own literal syntax, so that what is printed could be typed back in:

```
>>> "hello"
"hello"
>>> [1, 2, 3]
[1, 2, 3]
>>> Point { x: 3, y: 4 }
Point { x: 3, y: 4 }
>>> std.sys.page_size()
4096 B
```

Strings are shown quoted, which distinguishes the string `"42"` from the integer `42` and the empty string from no output at all.  `std.print` writes its argument unquoted and returns `∅`, so a call to it produces exactly one line rather than a line plus an echoed result.

### Errors

An error ends the entry that caused it and nothing else.  The session keeps its bindings and continues:

```
>>> a[9]
error: array index 9 out of range (length 2)
  --> <repl:4>:1:3
    |
  1 | a[9]
    |   ^
    |
>>> "still alive"
"still alive"
```

Diagnostics carry the same source excerpt and caret as in file mode, with the entry number standing in for a file name.  Parse errors, type errors, and runtime errors are all reported this way, and none of them ends the session.

### Non-Interactive Input

When standard input is not a terminal the REPL prints no banner and no prompts, so a piped script produces exactly its results:

```
$ printf '1 + 2\nlet x := 5\nx * x\n' | ngpl
3
25
```

This makes the REPL usable as a filter and gives the interpreter's own test suite a way to exercise it.

### Comparison with Other Languages

| Feature | Python | Julia | GHCi | Zig | NGPL |
|---------|--------|-------|------|-----|---------------|
| Block terminated by | empty line | `end` keyword | layout / `:{` `:}` | n/a (no REPL) | empty line |
| Bare expression shown | yes | yes | yes | n/a | yes |
| Statements at top level | yes (also in files) | yes (also in files) | via `let`/IO | n/a | REPL only |
| Definitions redefinable | yes | yes (with warning) | yes | n/a | yes |
| Auto-enter without entry point | no | no | n/a | n/a | yes |
| Prompts when piped | yes | no | yes | n/a | no |

The closest model is Python's, and the empty-line rule is taken from it directly.  The significant departure is that statements and definitions are separated in files but united in the REPL: a file keeps the property that all code is inside a named, reviewable unit, while the REPL — where the unit of work is the entry, not the file — does not need it.

Entering the REPL automatically when a file defines no startup function has no counterpart in these languages, and follows from the interpreter's role in a fast edit-evaluate-check loop: a library that cannot be run should still be explorable without a wrapper program.


Chapter 14: The Runtime — Termination and Backtraces
-----------------------------------------------------

### Terminating the Program

Two standard library functions end a program before its startup function returns.  They differ in what the parent process is told: `exit` reports a status the program chose, `abort` reports that the program died.

#### `std.exit(code)`

```
fn quit_early() → ∅:
    std.print("quitting")
    std.exit(42)
    std.print("unreachable")
```

`exit` terminates immediately with the given status.  Nothing after the call runs, and the startup function's own return value is not consulted — the two are alternative ways of choosing a status, and an explicit `exit` wins because it happened.

The argument must be in the range 0…255.  A POSIX exit status is a single byte, so a program exiting with 300 would be reported as having exited with 44; that silent truncation is rejected rather than performed:

```
std.exit(300)
error: std.exit: exit code 300 is outside the range 0…255 that a process
can report
```

This follows the language's general stance on overflow: a value that will not fit is an error, not a wrap.  It differs from C's `exit`, which accepts any `int` and truncates, and from Rust's `process::exit`, which does the same.

`exit` produces no diagnostic and no backtrace.  It is a deliberate act, not a failure.

#### `std.abort(signal)`

```
fn give_up() → ∅:
    std.abort()
```

`abort` terminates by raising a signal on the process, with that signal's handler reset to the default first, so the process really is killed by it and the parent sees the termination signal in its wait status rather than an ordinary exit.  A shell reports this as 128 plus the signal number: 134 for the default `SIGABRT`.

The signal argument is optional.  A missing, zero, or unrecognized signal number falls back to `SIGABRT`:

```
std.abort()        // SIGABRT — status 134
std.abort(15)      // SIGTERM — status 143
std.abort(999)     // not a signal, so SIGABRT — status 134
```

The fallback is deliberate rather than an oversight.  `abort` is called when a program has already concluded it cannot continue; refusing to terminate because the requested signal number was wrong would replace a controlled stop with an uncontrolled one, which is the worse outcome.  A wrong signal number is still a bug, but it is not a bug worth keeping a broken program alive over.

Unlike `exit`, `abort` reports where it was called from, since a program that aborts is one whose state needs explaining:

```
before abort
aborted: SIGABRT
backtrace (innermost call first):
  #0 give_up at program.nl:5:4
  #1 main at program.nl:10:4
```

### Backtraces

When a program ends abnormally the interpreter prints the chain of calls that led there, innermost first:

```
error: array index 9 out of range (length 2)
  --> program.nl:6:12
    |
  6 |     values[n]
    |            ^
    |
backtrace (innermost call first):
  #0 innermost at program.nl:6:11
  #1 middle at program.nl:9:14
  #2 outer at program.nl:12:11
  #3 main at program.nl:17:20
```

Each frame reports where execution had reached in that function, not merely where the function was entered, so the chain reads as a sequence of call sites.

Only the program's own functions appear.  The interpreter's internals are a separate matter, shown by `--interpreter-backtrace`, which is a tool for working on the interpreter rather than on a program written in the language.  The two are deliberately kept apart: a programmer debugging their own code is not helped by the evaluator's Python frames.

A backtrace is printed only when there is more than one frame.  For an error directly inside the startup function the diagnostic's caret has already pointed at the failing line, and a one-line backtrace repeating it would be noise.  `abort` is the exception, because it prints no caret diagnostic of its own; there a single frame is the only thing saying where the abort came from.

The recorded stack travels with the failure rather than being read from the interpreter afterwards, so a stack can never be reported against the wrong error — an error caught and recovered from leaves nothing behind to confuse a later, unrelated failure.

### Reading the Call Stack (`std.callstack`)

A program can inspect its own call stack at any point, not only when failing:

```
fn log_caller() → ∅:
    foreach frame := std.callstack():
        std.print(frame[0], " at line ", frame[1], " column ", frame[2])
```

`std.callstack()` returns an array of `(name, line, column)` tuples, innermost first.  Entry 0 is the function that called `callstack`, not `callstack` itself, so a function can name itself with `std.callstack()[0][0]` without accounting for the call it just made.

The stack describes only the interpreted program, matching what a backtrace would show.  It is a snapshot: the array does not change as the program continues, so it can be stored and examined later.

### Comparison with Other Languages

| Feature | C | Rust | Zig | Go | NGPL |
|---------|---|------|-----|-----|---------------|
| Exit with status | `exit(n)` | `process::exit(n)` | `std.process.exit(n)` | `os.Exit(n)` | `std.exit(n)` |
| Out-of-range status | truncated | truncated | `u8` required | truncated | error |
| Abort | `abort()` (SIGABRT only) | `process::abort()` | `@panic` | `panic` | `std.abort(signal)` |
| Choice of signal | via `raise` | no | no | no | yes |
| Backtrace on failure | no | opt in (`RUST_BACKTRACE`) | yes | yes | yes |
| Program-only frames | n/a | mixed with runtime | mixed with runtime | yes | yes |
| Read the stack at runtime | `backtrace(3)`, glibc | `Backtrace::capture` | `std.debug` | `runtime.Callers` | `std.callstack()` |

Zig requires a `u8` for the exit status, which reaches the same end as rejecting out-of-range values here, one step earlier — through the type rather than a check.  Adopting that would mean `std.exit` could not accept an untyped integer constant without an annotation, which is why the check is at the call instead.

Letting `abort` choose its signal has no counterpart in these languages, where abort means SIGABRT and nothing else.  It costs nothing to allow, and a program that wants to look to its parent as though it were terminated by SIGTERM has no other way to say so.
