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

