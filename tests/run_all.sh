#!/bin/bash
# Run all newlang test files and report a summary.
# Exit with non-zero status if any test file fails.

cd "$(dirname "$0")/.." || exit 1

tests=(
    tests/test_byte.nl
    tests/test_const.nl
    tests/test_errors.nl
    tests/test_fast.nl
    tests/test_foreach.nl
    tests/test_layout.nl
    tests/test_types.nl
    tests/sha256.nl
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
