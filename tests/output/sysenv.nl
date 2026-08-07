// Exact-value test for std.args and std.env.
//
// The output test runner supplies a fixed command line (sysenv.args)
// and a fixed set of environment variables (sysenv.env), so unlike the
// invariant tests in tests/test_sysenv.nl this program can check the
// values themselves.

@start
fn main() → ∅:
    std.print("count: ", std.args.count())
    foreach v := std.args.all():
        std.print("arg: [", v, "]")
    std.print("first: ", std.args.get(0))
    std.print("set: ", std.env.get("NGPL_TEST_VAR") ?? "<absent>")
    std.print("has set: ", std.env.has("NGPL_TEST_VAR"))
    // An empty value is a value: it must not read as absent.
    std.print("empty: [", std.env.get("NGPL_TEST_EMPTY") ?? "<absent>", "]")
    std.print("has empty: ", std.env.has("NGPL_TEST_EMPTY"))
    std.print("absent: ", std.env.get("NGPL_TEST_ABSENT") ?? "<absent>")
    std.print("has absent: ", std.env.has("NGPL_TEST_ABSENT"))
