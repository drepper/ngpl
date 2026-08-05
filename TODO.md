To Do List
==========

Work on all the issues without the checkmark.  Implement them on separate git branches.  Always
add test cases and adjust the language specification.  Once a to do item is complete add the
checkmark, commit the change, and change back to main.


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
