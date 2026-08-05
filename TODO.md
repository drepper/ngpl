To Do List
==========

Work on all the issues without the checkmark.  Implement them on separate git branches.  Always
add test cases and adjust the language specification.


[ ] allow lambda functions to have bodies of multiple statement.  Indicate using the usual syntax of
    colon at the end of { } block.

[ ] add @enumerate(CONTAINER) which creates an iterator that can be used as in
    foreach i,v := @enumerate([5,4,3,2,1]):

[ ] add static_assert, static_assert_eq etc to force the contained tests to be performed at compile time.
    If the expression is not compile-time constant raise a compilation error/crash the interpreter.
    add tests

[ ] add @typeof(EXPR) and @resultof(FCT).  These builtin functions return types which can be tested for
    equality with other types.  Use it in examples using static_assert_eq etc.  Depends on static_assert.
