# The one file the compiler is rooted in.
#
# There used to be a list here, in the order the sources had to be
# compiled in, and the same list again in the @build recipe in
# src/main.ngpl; the bootstrap compared stage 1 with stage 2 to keep
# the two in step.  Neither is needed now.  Every source says at its
# head what it is written against --
#
#     @import("./tokens.ngpl")
#
# -- and the compiler follows those from this one file, putting each
# file after everything it names.  The order of the sources is the
# program's own business again, written in the files that know it.
NGPLC_ROOT=src/main.ngpl

# Kept for whoever still spells it this way: one root is a list of one.
NGPLC_SOURCES=("$NGPLC_ROOT")
