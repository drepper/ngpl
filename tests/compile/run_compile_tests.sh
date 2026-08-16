#!/bin/bash
# The shared phase of the one test suite (tests/run_tests.sh drives it;
# it also runs on its own, and is what --impl=compiled selects): every
# program here is run by the bootstrap interpreter and compiled by
# ngplc and executed, and the two runs must agree.  The interpreter is
# the semantic authority.  A test that must behave differently per
# implementation conditionalizes on std.implementation.
#
# tNN_*.ngpl (NN < 90): outputs and exit codes must match exactly.
# t9N_*.ngpl: programs that stop themselves; both runs must fail after
#             printing the same successful prefix on stdout.

topdir=$(cd "$(dirname "$(realpath "$0")")/../.." && pwd) || exit 1
cd "$topdir" || exit 1
testdir=$topdir/tests/compile
workdir=$(mktemp -d) || exit 1
trap 'rm -rf "$workdir"' EXIT

pass=0
fail=0

for t in "$testdir"/t*.ngpl; do
    name=$(basename "$t" .ngpl)
    expect_abort=0
    case "$name" in
        t9*) expect_abort=1 ;;
    esac

    python -m interp --skip-tests "$t" > "$workdir/$name.interp.out" 2>/dev/null
    interp_rc=$?

    if ! python -m interp src/ngplc.ngpl -- "$t" -o "$workdir/$name.bin" \
            > "$workdir/$name.ngplc.out" 2>&1; then
        echo "FAIL $name: ngplc refused it"
        sed 's/^/    /' "$workdir/$name.ngplc.out" | head -5
        fail=$((fail + 1))
        continue
    fi

    "$workdir/$name.bin" > "$workdir/$name.native.out" 2>/dev/null
    native_rc=$?

    if [ $expect_abort -eq 1 ]; then
        if [ $interp_rc -eq 0 ] || [ $native_rc -eq 0 ]; then
            echo "FAIL $name: expected both to stop (interp $interp_rc, native $native_rc)"
            fail=$((fail + 1))
            continue
        fi
    else
        if [ $interp_rc -ne $native_rc ]; then
            echo "FAIL $name: exit codes differ (interp $interp_rc, native $native_rc)"
            fail=$((fail + 1))
            continue
        fi
    fi

    if ! diff -q "$workdir/$name.interp.out" "$workdir/$name.native.out" > /dev/null; then
        echo "FAIL $name: outputs differ"
        diff "$workdir/$name.interp.out" "$workdir/$name.native.out" | head -10 | sed 's/^/    /'
        fail=$((fail + 1))
        continue
    fi

    echo "ok   $name"
    pass=$((pass + 1))
done

echo
echo "compile conformance: $pass passed, $fail failed"
exit $((fail > 0))
