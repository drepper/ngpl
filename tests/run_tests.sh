#!/bin/bash
# Run NGPL test files and report a summary.
# With no arguments, runs all tests.  With arguments, runs only tests
# whose filename contains any of the given patterns.
# Exit with non-zero status if any test fails.

topdir=$(cd "$(dirname "$(realpath "$0")")/.." && pwd) || exit 1
cd "$topdir" || exit 1
testdir=$topdir/tests

all_tests=(
    "$testdir"/test_byte.nl
    "$testdir"/test_let.nl
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
    "$testdir"/test_lambda.nl
    "$testdir"/test_generate.nl
    "$testdir"/test_reshape.nl
    "$testdir"/test_catch.nl
    "$testdir"/test_concat.nl
    "$testdir"/test_arrows.nl
    "$testdir"/test_enumerate.nl
    "$testdir"/test_static_assert.nl
    "$testdir"/test_typeof.nl
    "$testdir"/test_fold.nl
    "$testdir"/test_curry.nl
    "$testdir"/test_sizeof_units.nl
    "$testdir"/test_unitof.nl
    "$testdir"/test_type_strict.nl
    "$testdir"/test_index_units.nl
    "$testdir"/sha256.nl
    "$testdir"/test_arena.nl
    "$testdir"/test_comptime_foreach.nl
    "$testdir"/test_comptime_introspect.nl
    "$testdir"/test_exit_code.nl
    "$testdir"/test_float.nl
    "$testdir"/test_format.nl
    "$testdir"/test_generic.nl
    "$testdir"/test_multidim.nl
    "$testdir"/test_pack.nl
    "$testdir"/test_power.nl
    "$testdir"/test_purity.nl
    "$testdir"/test_roots.nl
    "$testdir"/test_units.nl
    "$testdir"/test_view_assign.nl
    "$testdir"/test_type_alias.nl
    "$testdir"/test_struct.nl
    "$testdir"/test_move.nl
    "$testdir"/test_sysenv.nl
    "$testdir"/test_repr_c.nl
    "$testdir"/test_callstack.nl
    "$testdir"/test_discard.nl
    "$testdir"/test_scope_close.nl
    "$testdir"/test_borrow_foreach.nl
    "$testdir"/test_array_methods.nl
    "$testdir"/test_iterator.nl
    "$testdir"/test_while_binding.nl
    "$testdir"/test_try_return_type.nl
    "$testdir"/test_match.nl
    "$testdir"/test_unused_mut.nl
)

# Filter tests if command-line patterns are given.
if (($# > 0)); then
    tests=()
    for t in "${all_tests[@]}"; do
        name=$(basename "$t")
        for pat in "$@"; do
            if [[ $name == *"$pat"* ]]; then
                tests+=("$t")
                break
            fi
        done
    done
    if ((${#tests[@]} == 0)); then
        echo "No tests matched: $*"
        exit 1
    fi
else
    tests=("${all_tests[@]}")
fi

passed=0
failed=0
failures=()

for t in "${tests[@]}"; do
    if python -m interp --test "$t" 2>&1; then
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

# Run output-capture and REPL tests only when running all tests.
if (($# == 0)); then
    echo
    if python "$testdir"/run_output_tests.py 2>&1; then
        :
    else
        exit 1
    fi
    if python "$testdir"/run_repl_tests.py 2>&1; then
        :
    else
        exit 1
    fi
fi
