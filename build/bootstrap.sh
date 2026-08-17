#!/bin/bash
# The bootstrap chain, as the process in CLAUDE.md lays it out:
#
#   stage 1: the interpreted compiler compiles src/ngplc.ngpl
#   stage 2: the stage-1 binary compiles the same source
#   stage 3: the stage-2 binary compiles it once more
#
# Stages 2 and 3 must be byte-identical -- the fixed point -- and the
# verified stage-2 binary is installed as build/ngplc.  The chain is
# cached: with build/ngplc newer than the source, nothing runs.  Force
# a rebuild with --force.
set -e
topdir=$(cd "$(dirname "$(realpath "$0")")/.." && pwd)
cd "$topdir"
out=build/ngplc
src=src/ngplc.ngpl

if [[ $1 != --force && -x $out && $out -nt $src ]]; then
    exit 0
fi

work=$(mktemp -d) || exit 1
trap 'rm -rf "$work"' EXIT

echo "bootstrap: stage 1 -- the interpreted compiler compiles itself (minutes)" >&2
python -m interp --timeout="${NGPLI_TIMEOUT:-1800}" "$src" -- "$src" -o "$work/stage1"

echo "bootstrap: stage 2 -- the stage-1 binary compiles the source" >&2
"$work/stage1" "$src" -o "$work/stage2"

echo "bootstrap: stage 3 -- the stage-2 binary compiles the source" >&2
"$work/stage2" "$src" -o "$work/stage3"

if ! cmp -s "$work/stage2" "$work/stage3"; then
    echo "bootstrap: FAILED -- stage 2 and stage 3 differ" >&2
    exit 1
fi
echo "bootstrap: fixed point holds (stage2 == stage3)" >&2

mv "$work/stage2" "$out"
chmod +x "$out"
echo "bootstrap: installed $out" >&2
