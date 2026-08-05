#!/bin/bash
# Run all newlang test files and report a summary.
# Exit with non-zero status if any test file fails.

topdir=$(cd "$(dirname "$(realpath "$0")")/.." && pwd) || exit 1
cd "$topdir" || exit 1
testdir=$topdir/tests

tests=(
    "$testdir"/test_byte.nl
    "$testdir"/test_const.nl
    "$testdir"/test_errors.nl
    "$testdir"/test_fast.nl
    "$testdir"/test_foreach.nl
    "$testdir"/test_layout.nl
    "$testdir"/test_logic.nl
    "$testdir"/test_overflow.nl
    "$testdir"/test_wrap.nl
    "$testdir"/test_enum.nl
    "$testdir"/test_expected.nl
    "$testdir"/test_stepped_range.nl
    "$testdir"/test_types.nl
    "$testdir"/sha256.nl
)

passed=0
failed=0
failures=()

for t in "${tests[@]}"; do
    if python -m interp.main --test "$t" 2>&1; then
        ((passed++))
    else
        ((failed++))
        failures+=("$t")
    fi
    echo
done

echo "========================================"
echo "files: $((passed + failed))  passed: $passed  failed: $failed"
if ((failed > 0)); then
    echo "failures:"
    for f in "${failures[@]}"; do
        echo "  $f"
    done
    exit 1
fi
