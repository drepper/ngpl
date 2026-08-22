#!/bin/bash
# The NGPL test suite -- one suite for every implementation.
#
#   tests/*.ngpl        bootstrap-language tests, run by the Python
#                       interpreter (features the compiler does not
#                       carry yet live here, as separate files)
#   tests/compile/*     shared programs in the compiled subset; each is
#                       run by the interpreter AND compiled by ngplc
#                       and executed, and the two runs must agree.  A
#                       test that must behave differently per
#                       implementation conditionalizes on
#                       std.implementation.
#
# Usage: run_tests.sh [--impl=bootstrap|compiled|native|both|all] [pattern...]
#   --impl=bootstrap   only the interpreter's own tests
#   --impl=compiled    the shared conformance run, ngplc under the
#                      interpreter
#   --impl=native      the shared conformance run, the self-hosted
#                      ngplc binary (built and cached by
#                      build/bootstrap.sh; the first build takes
#                      minutes)
#   --impl=both        bootstrap + compiled (the default)
#   --impl=all         bootstrap + compiled + native
# With patterns, runs only bootstrap tests whose filename matches.
# Exit with non-zero status if any test fails.

impl_mode=both
patterns=()
for arg in "$@"; do
    case "$arg" in
        --impl=bootstrap|--impl=compiled|--impl=native|--impl=both|--impl=all)
            impl_mode=${arg#--impl=} ;;
        --impl=*)
            echo "unknown implementation '$arg'; bootstrap, compiled, native, both or all" >&2
            exit 1 ;;
        *)
            patterns+=("$arg") ;;
    esac
done

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
    "$testdir"/test_short_circuit.ngpl
    "$testdir"/test_callee_scope.ngpl
    "$testdir"/test_file_write.ngpl
    "$testdir"/test_implementation.ngpl
    "$testdir"/test_build.ngpl
    "$testdir"/test_unit_decay.ngpl
    "$testdir"/test_module.ngpl
    "$testdir"/test_arena.ngpl
    "$testdir"/test_comptime_foreach.ngpl
    "$testdir"/test_comptime_introspect.ngpl
    "$testdir"/test_exit_code.ngpl
    "$testdir"/test_float.ngpl
    "$testdir"/test_format.ngpl
    "$testdir"/test_generic.ngpl
    "$testdir"/test_multidim.ngpl
    "$testdir"/test_array_type.ngpl
    "$testdir"/test_untyped.ngpl
    "$testdir"/test_saturating.ngpl
    "$testdir"/test_no_return_type.ngpl
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
    "$testdir"/test_enum_type.ngpl
    "$testdir"/test_bootstrap.ngpl
    "$testdir"/test_int_width.ngpl
    "$testdir"/test_limits.ngpl
    "$testdir"/test_approx.ngpl
    "$testdir"/test_type_alias.ngpl
    "$testdir"/test_struct.ngpl
    "$testdir"/test_move.ngpl
    "$testdir"/test_sysenv.ngpl
    "$testdir"/test_repr_c.ngpl
    "$testdir"/test_writev.ngpl
    "$testdir"/test_field_units.ngpl
    "$testdir"/test_callstack.ngpl
    "$testdir"/test_discard.ngpl
    "$testdir"/test_scope_close.ngpl
    "$testdir"/test_borrow_foreach.ngpl
    "$testdir"/test_array_methods.ngpl
    "$testdir"/test_iterator.ngpl
    "$testdir"/test_walk_holds.ngpl
    "$testdir"/test_one_thing_twice.ngpl
    "$testdir"/test_evaluation_order.ngpl
    "$testdir"/test_enum_distinct.ngpl
    "$testdir"/test_division_failure.ngpl
    "$testdir"/test_while_binding.ngpl
    "$testdir"/test_try_return_type.ngpl
    "$testdir"/test_match.ngpl
    "$testdir"/test_unused_mut.ngpl
    "$testdir"/test_unused_value.ngpl
    "$testdir"/test_minmax.ngpl
    "$testdir"/test_float_overflow.ngpl
    "$testdir"/test_tuple_type.ngpl
    "$testdir"/test_char.ngpl
    "$testdir"/test_index_of.ngpl
    "$testdir"/test_element_of.ngpl
    "$testdir"/test_listable.ngpl
    "$testdir"/test_array_units.ngpl
    "$testdir"/test_length.ngpl
    "$testdir"/test_dict_set.ngpl
    "$testdir"/test_noreturn.ngpl
    "$testdir"/test_contracts.ngpl
    "$testdir"/test_loop_labels.ngpl
    "$testdir"/test_macros.ngpl
    "$testdir"/test_conditional_expr.ngpl
    "$testdir"/test_map.ngpl
)

# Every test file under tests/ must be in the list above: a file the
# runner does not know about is a test that silently never runs.
missing=()
for f in "$testdir"/*.ngpl; do
    found=0
    for t in "${all_tests[@]}"; do
        if [[ $t == "$f" ]]; then
            found=1
            break
        fi
    done
    if ((found == 0)); then
        missing+=("$f")
    fi
done
if ((${#missing[@]} > 0)); then
    echo "error: test files not registered in run_tests.sh:"
    for f in "${missing[@]}"; do
        echo "  $f"
    done
    exit 1
fi

# Filter tests if command-line patterns are given.
if ((${#patterns[@]} > 0)); then
    tests=()
    for t in "${all_tests[@]}"; do
        name=$(basename "$t")
        for pat in "${patterns[@]}"; do
            if [[ $name == *"$pat"* ]]; then
                tests+=("$t")
                break
            fi
        done
    done
    if ((${#tests[@]} == 0)); then
        echo "No tests matched: ${patterns[*]}"
        exit 1
    fi
else
    tests=("${all_tests[@]}")
fi

if [[ $impl_mode == compiled ]]; then
    exec "$testdir"/compile/run_compile_tests.sh
fi
if [[ $impl_mode == native ]]; then
    exec "$testdir"/compile/run_compile_tests.sh --compiler=native
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
if ((${#patterns[@]} == 0)); then
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
    # The specification is the normative reference, so an example in it
    # the parser would refuse is a defect in the document.
    if python "$testdir"/check_spec_signatures.py 2>&1; then
        :
    else
        exit 1
    fi

    # Every test file accounts for its own diagnostics, so the suite
    # passes with warnings treated as errors.  A new warning nothing
    # expects shows up here rather than in the scroll-back.
    echo
    echo "checking ${#all_tests[@]} test files with -Werror"
    werror_failures=()
    for t in "${all_tests[@]}"; do
        if ! python -m interp -Werror --test "$t" > /dev/null 2>&1; then
            werror_failures+=("$t")
        fi
    done
    echo
    if ((${#werror_failures[@]} > 0)); then
        echo "-Werror check: FAILED"
        for f in "${werror_failures[@]}"; do
            echo "  $f"
            python -m interp -Werror --test "$f" 2>&1 | grep '^error:' | head -3
        done
        exit 1
    fi
    echo "-Werror check: ok. ${#all_tests[@]} files clean"
fi

# The shared conformance run: every program under tests/compile/ goes
# through the interpreter and through ngplc, and the runs must agree.
if [[ $impl_mode == both || $impl_mode == all ]] && ((${#patterns[@]} == 0)); then
    echo
    if ! "$testdir"/compile/run_compile_tests.sh; then
        exit 1
    fi
fi

# And with --impl=all, once more under the self-hosted binary: the
# same programs, the same agreement, the compiler compiled by itself.
if [[ $impl_mode == all ]] && ((${#patterns[@]} == 0)); then
    echo
    if ! "$testdir"/compile/run_compile_tests.sh --compiler=native; then
        exit 1
    fi
fi
