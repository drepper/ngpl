#!/bin/bash
# Run NGPL test files and report a summary.
# With no arguments, runs all tests.  With arguments, runs only tests
# whose filename contains any of the given patterns.
# Exit with non-zero status if any test fails.

topdir=$(cd "$(dirname "$(realpath "$0")")/.." && pwd) || exit 1
cd "$topdir" || exit 1
testdir=$topdir/tests

all_tests=(
    "$testdir"/test_byte.ngpl
    "$testdir"/test_let.ngpl
    "$testdir"/test_errors.ngpl
    "$testdir"/test_fast.ngpl
    "$testdir"/test_foreach.ngpl
    "$testdir"/test_layout.ngpl
    "$testdir"/test_logic.ngpl
    "$testdir"/test_overflow.ngpl
    "$testdir"/test_wrap.ngpl
    "$testdir"/test_enum.ngpl
    "$testdir"/test_expected.ngpl
    "$testdir"/test_stepped_range.ngpl
    "$testdir"/test_types.ngpl
    "$testdir"/test_lambda.ngpl
    "$testdir"/test_generate.ngpl
    "$testdir"/test_reshape.ngpl
    "$testdir"/test_catch.ngpl
    "$testdir"/test_concat.ngpl
    "$testdir"/test_arrows.ngpl
    "$testdir"/test_enumerate.ngpl
    "$testdir"/test_static_assert.ngpl
    "$testdir"/test_typeof.ngpl
    "$testdir"/test_fold.ngpl
    "$testdir"/test_curry.ngpl
    "$testdir"/test_sizeof_units.ngpl
    "$testdir"/test_unitof.ngpl
    "$testdir"/test_type_strict.ngpl
    "$testdir"/test_index_units.ngpl
    "$testdir"/sha256.ngpl
    "$testdir"/test_arena.ngpl
    "$testdir"/test_comptime_foreach.ngpl
    "$testdir"/test_comptime_introspect.ngpl
    "$testdir"/test_exit_code.ngpl
    "$testdir"/test_float.ngpl
    "$testdir"/test_format.ngpl
    "$testdir"/test_generic.ngpl
    "$testdir"/test_multidim.ngpl
    "$testdir"/test_pack.ngpl
    "$testdir"/test_power.ngpl
    "$testdir"/test_purity.ngpl
    "$testdir"/test_roots.ngpl
    "$testdir"/test_units.ngpl
    "$testdir"/test_view_assign.ngpl
    "$testdir"/test_slice_param.ngpl
    "$testdir"/test_matrix_param.ngpl
    "$testdir"/test_if.ngpl
    "$testdir"/test_hints.ngpl
    "$testdir"/test_sum.ngpl
    "$testdir"/test_type_alias.ngpl
    "$testdir"/test_struct.ngpl
    "$testdir"/test_move.ngpl
    "$testdir"/test_sysenv.ngpl
    "$testdir"/test_repr_c.ngpl
    "$testdir"/test_callstack.ngpl
    "$testdir"/test_discard.ngpl
    "$testdir"/test_scope_close.ngpl
    "$testdir"/test_borrow_foreach.ngpl
    "$testdir"/test_array_methods.ngpl
    "$testdir"/test_iterator.ngpl
    "$testdir"/test_while_binding.ngpl
    "$testdir"/test_try_return_type.ngpl
    "$testdir"/test_match.ngpl
    "$testdir"/test_unused_mut.ngpl
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
