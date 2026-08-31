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
    ngplc() { python -m interp "$NGPLC_ROOT" -- "$@"; }
fi

pass=0
fail=0

for t in "$testdir"/t*.ngpl; do
    name=$(basename "$t" .ngpl)
    expect_abort=0
    native_only=0
    case "$name" in
        t9*) expect_abort=1 ;;
        # t8N: what only a compiled program can do.  The language
        # guarantees a tail call spends no stack, and the bootstrap
        # interpreter does not implement that, so there is nothing to
        # compare against here: the program says whether it is right by
        # asserting, and leaving with 0 is the whole of the check.
        t8*) native_only=1 ;;
    esac

    interp_rc=0
    if [ $native_only -eq 0 ]; then
        python -m interp --skip-tests "$t" > "$workdir/$name.interp.out" 2>/dev/null
        interp_rc=$?
    fi

    if ! ngplc "$t" -o "$workdir/$name.bin" \
            > "$workdir/$name.ngplc.out" 2>&1; then
        echo "FAIL $name: ngplc refused it"
        sed 's/^/    /' "$workdir/$name.ngplc.out" | head -5
        fail=$((fail + 1))
        continue
    fi

    "$workdir/$name.bin" > "$workdir/$name.native.out" \
        2> "$workdir/$name.native.err"
    native_rc=$?

    if [ $native_only -eq 1 ]; then
        # Leaving with 0 is the whole of the check, unless the test
        # pins what it writes: a routine that writes nothing passes
        # every assertion, so what is printed has to be looked at.
        if [ $native_rc -ne 0 ]; then
            echo "FAIL $name: the compiled program stopped with $native_rc"
            sed 's/^/    /' "$workdir/$name.native.out" | head -5
            fail=$((fail + 1))
        elif [ -f "$testdir/$name.expected" ] \
                && ! diff -u "$testdir/$name.expected" \
                        "$workdir/$name.native.out" > "$workdir/$name.diff"; then
            echo "FAIL $name: not what it says it writes"
            sed 's/^/    /' "$workdir/$name.diff" | head -8
            fail=$((fail + 1))
        else
            echo "ok   $name"
            pass=$((pass + 1))
        fi
        continue
    fi

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
        # What a stop says on the error stream, where a test pins it.
        # The interpreter is not held to this: it names a position on
        # every frame and the compiled program names only the function,
        # which is the one place the two are allowed to differ.
        if [ -f "$testdir/$name.err.expected" ] \
                && ! diff -u "$testdir/$name.err.expected" \
                        "$workdir/$name.native.err" > "$workdir/$name.ediff"; then
            echo "FAIL $name: not what it says it reports"
            sed 's/^/    /' "$workdir/$name.ediff" | head -12
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
# directory under multi/ holds its files and a `root` naming the one
# the program is rooted in; the rest are reached from it by the @import
# lines they carry, which is also what settles the order they are
# compiled in -- a file goes in after everything it names.
#
# A directory whose files carry a @build recipe is compiled a second
# time through --build, and the two binaries must be byte-identical:
# that is what says the recipe is rooted in the file `root` names,
# rather than something that merely also works.
# ---------------------------------------------------------------------------
for d in "$testdir"/multi/*/; do
    [ -f "$d/root" ] || continue
    name=multi-$(basename "$d")
    files=()
    while read -r f; do
        [ -n "$f" ] && files+=("$d$f")
    done < "$d/root"

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

    recipe=$(grep -l '@build' "$d"*.ngpl 2>/dev/null | head -1)
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
# Recipes that build more than one thing: each directory under recipes/
# holds its sources, a recipe.ngpl carrying the @build function, a
# `built` naming the files the recipe should produce in the order it
# adds them, and an `expected` holding what running them in that order
# prints.
#
# The directory is copied into the work area first, because what a
# recipe names is named from where the recipe is: a build run in the
# source tree would write its binaries there.  The interpreter reads
# the same recipe -- it builds nothing, but the recipe has to be one it
# accepts, since it is the semantic authority for what a recipe may say.
#
# Where a recipe adds more than one, -o has nothing to name and must be
# refused rather than silently applied to one of them.
# ---------------------------------------------------------------------------
echo
for d in "$testdir"/recipes/*/; do
    [ -f "$d/recipe.ngpl" ] || continue
    name=recipe-$(basename "$d")
    src="$workdir/$name.src"
    rm -rf "$src"
    cp -r "$d" "$src"

    if ! python -m interp --skip-tests "$src/recipe.ngpl" \
            > "$workdir/$name.interp.out" 2>&1; then
        echo "FAIL $name: the interpreter refused the recipe"
        sed 's/^/    /' "$workdir/$name.interp.out" | head -5
        fail=$((fail + 1))
        continue
    fi

    # The compiler writes files and not directories, so what the
    # recipe names has to be there.  `built` says where each goes.
    while read -r f; do
        [ -n "$f" ] && mkdir -p "$src/$(dirname "$f")"
    done < "$d/built"

    if ! ngplc --build "$src/recipe.ngpl" > "$workdir/$name.out" 2>&1; then
        echo "FAIL $name: --build refused the recipe"
        sed 's/^/    /' "$workdir/$name.out" | head -5
        fail=$((fail + 1))
        continue
    fi

    : > "$workdir/$name.ran"
    missing=""
    while read -r f; do
        [ -n "$f" ] || continue
        if [ ! -x "$src/$f" ]; then
            missing=$f
            break
        fi
        "$src/$f" >> "$workdir/$name.ran" 2>&1
    done < "$d/built"
    if [ -n "$missing" ]; then
        echo "FAIL $name: the recipe wrote no '$missing'"
        fail=$((fail + 1))
        continue
    fi
    if ! diff -u "$d/expected" "$workdir/$name.ran" > "$workdir/$name.diff"; then
        echo "FAIL $name: what it built answers differently"
        sed 's/^/    /' "$workdir/$name.diff" | head -10
        fail=$((fail + 1))
        continue
    fi

    if [ "$(grep -c . "$d/built")" -gt 1 ]; then
        if ngplc --build "$src/recipe.ngpl" -o "$workdir/$name.one" \
                > "$workdir/$name.o.out" 2>&1; then
            echo "FAIL $name: -o was taken for a recipe that adds several"
            fail=$((fail + 1))
            continue
        fi
        if ! grep -q "names one file" "$workdir/$name.o.out"; then
            echo "FAIL $name: -o was refused, but not in those words"
            sed 's/^/    /' "$workdir/$name.o.out" | head -3
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
# The same program, laid out two ways, hashes its functions the same.
# Nothing either program prints could show this, so the bill of
# materials is what is compared.
# ---------------------------------------------------------------------------
echo
ngplc "$topdir"/tests/compile/t60_layout_indent.ngpl -o "$workdir"/lay_a >/dev/null 2>&1
ngplc "$topdir"/tests/compile/t61_layout_braces.ngpl -o "$workdir"/lay_b >/dev/null 2>&1
if python "$topdir"/tests/compile/check_layout_hashes.py \
        "$workdir"/lay_a "$workdir"/lay_b; then
    pass=$((pass + 1))
else
    fail=$((fail + 1))
fi

# ---------------------------------------------------------------------------
# What the compiler worked out about how long each binding lives.  The
# program's output says nothing about this -- the three answers all run
# the same -- so the decision log is what tells them apart, and this is
# where the three are pinned:  a &mut handed to a pure function
# answering a number does not extend anything, and one handed to an
# impure function or to a pure function that could answer it back runs
# to the end of the scope.
# ---------------------------------------------------------------------------
echo
lifelog=$(ngplc --log=json "$topdir"/tests/compile/t59_lifetimes.ngpl \
                -o "$workdir"/t59.life 2>/dev/null \
          | grep '"decision": "lifetime"' | grep '"function": "main"')
life_ok=1
for want in '"name": "a",.*"escapes": false' \
            '"name": "b",.*"escapes": true' \
            '"name": "c",.*"escapes": true'; do
    if ! echo "$lifelog" | grep -qE "$want"; then
        echo "FAIL lifetimes: no line matching $want"
        life_ok=0
    fi
done
# and the one nothing reads is warned about, by number
if ! ngplc "$topdir"/tests/compile/t59_lifetimes.ngpl -o "$workdir"/t59.life 2>&1 \
     | grep -q 'warning\[2421\]'; then
    : # t97 has no unused binding of its own; the warning is pinned below
fi
unused=$(printf '@start\n@impure\nfn main():\n    let idle : i64 = 1\n    std.println("x")\n' \
         > "$workdir"/unused.ngpl; ngplc "$workdir"/unused.ngpl -o "$workdir"/unused.bin 2>&1 \
         | grep -c 'warning\[2421\]')
if [ "$unused" != "1" ]; then
    echo "FAIL lifetimes: a binding nothing reads drew $unused warnings, wanted 1"
    life_ok=0
fi
if [ $life_ok -eq 1 ]; then
    echo "ok   lifetimes: the three &mut answers, and the binding nothing reads"
    pass=$((pass + 1))
else
    fail=$((fail + 1))
fi

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# What the compiler says no to.
#
# tests/compile/ asks every program to compile and tests/output/ drives
# the interpreter, so until now what ngplc refused was checked by hand.
# A refusal is a promise as much as a translation is: it says this
# program is not one, and in these words.  Each pair here is one
# refusal and what it said.
#
# The path is given relative to the tree so that the message a
# diagnostic carries is the same on every machine.
# ---------------------------------------------------------------------------
echo
for r in "$testdir"/refuse/*.ngpl; do
    [ -e "$r" ] || break
    name=$(basename "$r" .ngpl)
    rel="tests/compile/refuse/$name.ngpl"
    ( cd "$topdir" && ngplc "$rel" -o "$workdir/$name.bin" ) \
        > "$workdir/$name.raw" 2>&1
    rc=$?
    # Under --compiler=interp the compiler is itself a program the
    # interpreter is checking, and it says its piece about src/ before
    # it says anything about the file under test.  What is being pinned
    # here is what it said about the file under test, so the comparison
    # begins at the first line that names it.
    sed -n "\|$rel|,\$p" "$workdir/$name.raw" > "$workdir/$name.refuse"
    if [ $rc -eq 0 ]; then
        echo "FAIL refuse/$name: the compiler accepted it"
        fail=$((fail + 1))
    elif ! diff -u "$testdir/refuse/$name.expected" "$workdir/$name.refuse" \
            > "$workdir/$name.rdiff"; then
        echo "FAIL refuse/$name: refused, but not in those words"
        sed 's/^/    /' "$workdir/$name.rdiff" | head -8
        fail=$((fail + 1))
    else
        echo "ok   refuse/$name"
        pass=$((pass + 1))
    fi
done

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
