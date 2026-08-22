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
#
# --compiler=interp   ngplc run by the bootstrap interpreter (default)
# --compiler=native   the self-hosted ngplc binary, built (and cached)
#                     by build/bootstrap.sh -- the first build takes
#                     minutes, every later run finds it ready

topdir=$(cd "$(dirname "$(realpath "$0")")/../.." && pwd) || exit 1

compiler=interp
for arg in "$@"; do
    case "$arg" in
        --compiler=interp|--compiler=native) compiler=${arg#--compiler=} ;;
        --sweep) ;;
        *) echo "unknown option '$arg'; --compiler=interp, --compiler=native or --sweep" >&2
           exit 1 ;;
    esac
done

# Forward progress, guaranteed: any single interpreter invocation that
# has not finished in this many seconds is stopped with a backtrace
# rather than hanging the suite.  Override by exporting NGPLI_TIMEOUT.
export NGPLI_TIMEOUT=${NGPLI_TIMEOUT:-900}
cd "$topdir" || exit 1
testdir=$topdir/tests/compile
workdir=$(mktemp -d) || exit 1
trap 'rm -rf "$workdir"' EXIT

source "$topdir"/build/sources.sh
if [[ $compiler == native ]]; then
    "$topdir"/build/bootstrap.sh || exit 1
    ngplc() { "$topdir"/build/ngplc "$@"; }
else
    ngplc() { python -m interp "${NGPLC_SOURCES[@]}" -- "$@"; }
fi

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

    if ! ngplc "$t" -o "$workdir/$name.bin" \
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
        # A stop leaves through exit with a status the runtime reserves,
        # never through a signal, and both implementations use the same
        # number.  Asserting only "nonzero" was how the 1-against-134
        # fork stayed invisible for as long as it did.
        if [ $interp_rc -ne $native_rc ]; then
            echo "FAIL $name: stopped with different codes (interp $interp_rc, native $native_rc)"
            fail=$((fail + 1))
            continue
        fi
        if [ $native_rc -lt 64 ] || [ $native_rc -gt 127 ]; then
            echo "FAIL $name: stopped with $native_rc, which is outside the 64-127 the runtime reserves"
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

# ---------------------------------------------------------------------------
# Multi-file programs: several sources read as if they were one.  Each
# directory under multi/ holds its files and a `sources` naming them in
# the order they are compiled, which is part of the program -- an enum
# must be declared before it is used as a type.
#
# A directory whose files carry a @build recipe is compiled a second
# time through --build, and the two binaries must be byte-identical:
# that is what says the recipe names exactly the files `sources` does,
# rather than something that merely also works.
# ---------------------------------------------------------------------------
for d in "$testdir"/multi/*/; do
    [ -f "$d/sources" ] || continue
    name=multi-$(basename "$d")
    files=()
    while read -r f; do
        [ -n "$f" ] && files+=("$d$f")
    done < "$d/sources"

    python -m interp --skip-tests "${files[@]}" \
        > "$workdir/$name.interp.out" 2>/dev/null
    interp_rc=$?

    if ! ngplc "${files[@]}" -o "$workdir/$name.bin" \
            > "$workdir/$name.ngplc.out" 2>&1; then
        echo "FAIL $name: ngplc refused it"
        sed 's/^/    /' "$workdir/$name.ngplc.out" | head -5
        fail=$((fail + 1))
        continue
    fi
    "$workdir/$name.bin" > "$workdir/$name.native.out" 2>/dev/null
    native_rc=$?

    if [ $interp_rc -ne $native_rc ]; then
        echo "FAIL $name: exit codes differ (interp $interp_rc, native $native_rc)"
        fail=$((fail + 1))
        continue
    fi
    if ! diff -q "$workdir/$name.interp.out" "$workdir/$name.native.out" > /dev/null; then
        echo "FAIL $name: outputs differ"
        diff "$workdir/$name.interp.out" "$workdir/$name.native.out" | head -10 | sed 's/^/    /'
        fail=$((fail + 1))
        continue
    fi

    recipe=$(grep -l '@build' "${files[@]}" 2>/dev/null | head -1)
    if [ -n "$recipe" ]; then
        if ! ngplc --build "$recipe" -o "$workdir/$name.build.bin" \
                > "$workdir/$name.build.out" 2>&1; then
            echo "FAIL $name: --build refused the recipe"
            sed 's/^/    /' "$workdir/$name.build.out" | head -5
            fail=$((fail + 1))
            continue
        fi
        if ! cmp -s "$workdir/$name.bin" "$workdir/$name.build.bin"; then
            echo "FAIL $name: --build produced a different binary than the file list"
            fail=$((fail + 1))
            continue
        fi
    fi

    echo "ok   $name"
    pass=$((pass + 1))
done

# ---------------------------------------------------------------------------
# Shared test files: bootstrap suite files whose whole @test surface
# sits inside the compiled subset.  Each is compiled and run with
# --test, and stdout, stderr and the exit code must match the
# interpreter's byte for byte.  The list grows as the subset grows.
# ---------------------------------------------------------------------------
# --sweep: report suite files that already run identically under both
# implementations but are not in the list below.  The list is kept by
# hand, and a hand-kept list drifts behind what the compiler can do;
# this says so rather than leaving it to be noticed.
sweep_only=0
for a in "$@"; do
    case "$a" in --sweep) sweep_only=1 ;; esac
done

shared_tests=(
    test_arrows
    test_byte
    test_callee_scope
    test_concat
    test_evaluation_order
    test_enum_distinct
    test_division_failure
    test_exit_code
    test_generate
    test_hints
    test_if
    test_iterator
    test_lambda
    test_module
    test_match_enum
    test_noreturn
    test_reshape
    test_short_circuit
    test_stepped_range
    test_walk_holds
    test_one_thing_twice
    test_while_binding
    test_wrap
)

if [ $sweep_only -eq 1 ]; then
    missing=0
    for t in "$topdir"/tests/test_*.ngpl; do
        name=$(basename "$t" .ngpl)
        case " ${shared_tests[*]} " in *" $name "*) continue ;; esac
        ngplc "$t" -o "$workdir/$name.bin" >/dev/null 2>&1 || continue
        "$workdir/$name.bin" --test > "$workdir/$name.sn" 2> "$workdir/$name.sne"
        python3 -m interp --test "$t" > "$workdir/$name.si" 2> "$workdir/$name.sie" || true
        if cmp -s "$workdir/$name.si" "$workdir/$name.sn" &&
           cmp -s "$workdir/$name.sie" "$workdir/$name.sne"; then
            echo "could be shared: $name"
            missing=$((missing + 1))
        fi
    done
    if [ $missing -eq 0 ]; then
        echo "sweep: the shared list is current"
    else
        echo "sweep: $missing file(s) could be shared and are not"
    fi
    exit $missing
fi


for name in "${shared_tests[@]}"; do
    t=$topdir/tests/$name.ngpl
    if ! ngplc "$t" -o "$workdir/$name.bin" \
            > "$workdir/$name.ngplc.out" 2>&1; then
        echo "FAIL $name: ngplc refused it"
        sed 's/^/    /' "$workdir/$name.ngplc.out" | head -5
        fail=$((fail + 1))
        continue
    fi
    python -m interp --test "$t" > "$workdir/$name.i.out" 2> "$workdir/$name.i.err"
    irc=$?
    "$workdir/$name.bin" --test > "$workdir/$name.c.out" 2> "$workdir/$name.c.err"
    crc=$?
    if [ "$irc" -ne "$crc" ] \
            || ! cmp -s "$workdir/$name.i.out" "$workdir/$name.c.out" \
            || ! cmp -s "$workdir/$name.i.err" "$workdir/$name.c.err"; then
        echo "FAIL $name: the --test runs disagree (interp rc=$irc, native rc=$crc)"
        diff "$workdir/$name.i.err" "$workdir/$name.c.err" | head -5
        fail=$((fail + 1))
    else
        echo "ok   $name (--test)"
        pass=$((pass + 1))
    fi
done

# ---------------------------------------------------------------------------
# The shape of the binaries themselves.  Everything above compares what
# a compiled program prints; this asserts what the file it arrived in
# looks like -- the segment permissions, the RELRO region, the
# non-executable stack, the symbol table's ordering and names, and the
# runtime routines that a program out of reach of them does not carry.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# diag_codes() is what @expect is held to, and it is a hand-written
# list beside hand-written derrc/dwarn calls.  A number drawn but not
# listed is an expectation that would quietly pass; a number listed but
# not drawn is one that would always fail.  Both are checked here
# rather than trusted.
# ---------------------------------------------------------------------------
echo
drawn=$(grep -rho 'derrc(\([^,]*\), *[0-9]\{4\}\|dwarn(\([^,]*\), *[0-9]\{4\}' \
            "$topdir"/src/*.ngpl | grep -o '[0-9]\{4\}$' | sort -u)
listed=$(sed -n '/^fn diag_codes/,/^$/p' "$topdir"/src/check.ngpl \
             | grep -o '[0-9]\{4\}' | sort -u)
if [ "$drawn" = "$listed" ]; then
    echo "ok   diag_codes() lists the $(echo "$drawn" | wc -l) numbers the compiler draws"
    pass=$((pass + 1))
else
    echo "FAIL diag_codes() and the derrc/dwarn calls disagree"
    diff <(echo "$listed") <(echo "$drawn") | sed 's/^</    listed, never drawn: /;s/^>/    drawn, never listed: /'
    fail=$((fail + 1))
fi

echo
if python "$topdir"/tests/compile/run_elf_tests.py "--compiler=$compiler"; then
    :
else
    fail=$((fail + 1))
fi

echo
echo "compile conformance ($compiler): $pass passed, $fail failed"
exit $((fail > 0))
