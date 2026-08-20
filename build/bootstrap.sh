#!/bin/bash
# The bootstrap chain, as the process in CLAUDE.md lays it out:
#
#   stage 1: the interpreted compiler compiles the compiler's sources
#   stage 2: the stage-1 binary compiles the same sources
#   stage 3: the stage-2 binary compiles them once more
#
# Stages 2 and 3 must be byte-identical -- the fixed point -- and the
# verified stage-2 binary is installed as build/ngplc.  The chain is
# cached: with build/ngplc newer than every source, nothing runs.  Force
# a rebuild with --force.
set -e
topdir=$(cd "$(dirname "$(realpath "$0")")/.." && pwd)
cd "$topdir"
out=build/ngplc
source build/sources.sh

# The build is out of date when any one source is newer than it, which
# is not something `-nt` says in one test.
stale=0
[[ -x $out ]] || stale=1
for s in "${NGPLC_SOURCES[@]}"; do
    [[ $s -nt $out ]] && stale=1
done
if [[ $1 != --force && $stale -eq 0 ]]; then
    exit 0
fi

work=$(mktemp -d) || exit 1
trap 'rm -rf "$work"' EXIT

# Stage 1 runs under the interpreter, which reads a @build recipe but
# has no --build of its own, so it is handed the list above.  Stages 2
# and 3 are compilers, and take the list from the recipe in
# src/main.ngpl.  Comparing stage 1 with stage 2 therefore checks the
# two lists against each other: if the recipe and this script ever name
# different files, or the same files in a different order, the binaries
# differ and the bootstrap says so.
echo "bootstrap: stage 1 -- the interpreted compiler compiles itself (minutes)" >&2
python -m interp --timeout="${NGPLI_TIMEOUT:-1800}" "${NGPLC_SOURCES[@]}" \
       -- "${NGPLC_SOURCES[@]}" -o "$work/stage1"

echo "bootstrap: stage 2 -- the stage-1 binary compiles the sources its recipe names" >&2
"$work/stage1" --build src/main.ngpl -o "$work/stage2"

echo "bootstrap: stage 3 -- the stage-2 binary compiles them once more" >&2
"$work/stage2" --build src/main.ngpl -o "$work/stage3"

if ! cmp -s "$work/stage2" "$work/stage3"; then
    echo "bootstrap: FAILED -- stage 2 and stage 3 differ" >&2
    exit 1
fi
if ! cmp -s "$work/stage1" "$work/stage2"; then
    echo "bootstrap: FAILED -- stage 1 and stage 2 differ, so the @build recipe in" >&2
    echo "  src/main.ngpl and the list in build/sources.sh do not name the same" >&2
    echo "  files in the same order" >&2
    exit 1
fi
echo "bootstrap: fixed point holds (stage1 == stage2 == stage3)" >&2

mv "$work/stage2" "$out"
chmod +x "$out"
echo "bootstrap: installed $out" >&2
