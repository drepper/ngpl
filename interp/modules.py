"""What a program is made of, once a file can be a namespace.

A **module** is a file and everything reached from it by the plain
`@import("x")` form: those files are read in ahead of it and their names
are its names, which is what an import has always meant here.  A *bound*
import is the new thing:

    let m := @import("lib")

which starts a module of its own.  Nothing of it is visible except
through `m`, and then only what it marked `@export`.

That is the whole of the distinction, and it is what makes the change
affordable: a program with no bound import is one module, its names are
not qualified at all, and it behaves exactly as it did.  Qualification
appears only where a program asks for it.

Identity is the resolved path: two `@import`s of one file give two
bindings of one module, so its types are the same type and its globals
the same storage.  A module is loaded once however often it is bound.

The prefix a module's names carry is its number -- `m3.` -- rather than
anything drawn from the path, because a path is not a name: two files
may share a stem, a path may hold characters a name may not, and the
prefix is never written by a program.  What is written in a diagnostic
is the bare name; the prefix is a key, not a spelling.
"""

import os


class Module:
    """One namespace: a file, what it reads in plainly, and what it binds.

    `defs` is what the parser made of its text, in order.  `bindings`
    maps the name a bound import was given to the module it names, and
    `exports` is what this module lets others name.
    """

    __slots__ = ("index", "root", "paths", "text", "starts", "defs",
                 "bindings", "exports")

    def __init__(self, index: int, root: str):
        self.index = index
        # the file the module is rooted in, and its identity
        self.root = root
        # every file read into it, the plain imports first
        self.paths: list[str] = []
        self.text: str = ""
        self.starts: list[int] = []
        self.defs: list = []
        self.bindings: dict[str, int] = {}
        self.exports: set[str] = set()

    @property
    def prefix(self) -> str:
        """What this module's names are keyed under.

        The first module -- the one the program is rooted in -- takes no
        prefix, so a program of one module is keyed exactly as it was
        before there were modules at all.
        """
        return "" if self.index == 0 else f"m{self.index}"

    def qualify(self, name: str) -> str:
        """The key a name of this module is installed and found under."""
        return f"{self.prefix}.{name}" if self.prefix else name


def bare_name(key: str) -> str:
    """The name a key spells, for a diagnostic to say.

    A prefix is a key and not a spelling, so nothing a program reads
    ever shows one.
    """
    if key.startswith("m") and "." in key:
        head, rest = key.split(".", 1)
        if head[1:].isdigit():
            return rest
    return key


_KEY = __import__("re").compile(r"(?<![0-9A-Za-z_.])m[0-9]+\.(?=[A-Za-z_])")


def as_written(message: str) -> str:
    """A message with the keys taken back out of it.

    A module's prefix is how its names are told apart, not how they are
    spelled: what a program wrote was `Point`, and that is what it is
    told about.  The keys are stripped where a message is shown rather
    than where it is made, so that nothing making one has to remember.
    """
    return _KEY.sub("", message)


def file_at(m, line: int) -> str:
    """The file of a module a line falls in.

    A module is its root file and everything it reads in plainly, read
    into one text; which of them a definition was written in is the
    last one that begins at or before it.  It matters because a name a
    file asks for is looked for beside *that* file, not beside the one
    the module happens to be rooted in.
    """
    where = m.paths[0] if m.paths else m.root
    for k, st in enumerate(m.starts):
        if st <= line:
            where = m.paths[k]
        else:
            break
    return where


def module_of_path(mods, path: str):
    """The module rooted in this file, or None where none is."""
    real = os.path.realpath(path)
    for m in mods:
        if os.path.realpath(m.root) == real:
            return m
    return None


def load(roots, paths_asked, read_program, resolve, import_error,
         note_source=None):
    """Every module a program is made of, the root one first.

    `read_program` is what reads a module's own text -- the file it is
    rooted in and everything it imports plainly -- `resolve` answers
    where a name is to be found or says so itself, and `import_error` is
    what to raise for a ring.  All three are handed in so that this file
    does not have to know how a file is found or read.  `note_source`,
    where it is given, is told the text so far before each module is
    lexed, so that a mistake in one is shown against the text it was
    written in rather than against nothing.

    The text of every module is joined into one, in load order, and each
    module's lines are shifted to where its text lands: a diagnostic
    then points into one text and names one file, exactly as it did when
    a program was one text and nothing more.
    """
    from interp.lexer import tokenize, process_indentation
    from interp.parser import Parser
    from interp.ast import ImportExpr, VarDef

    mods: list[Module] = []
    by_path: dict[str, int] = {}
    pieces: list[str] = []
    all_starts: list[int] = []
    all_paths: list[str] = []
    lines = 0

    def take(root: str, asked: str | None, being: list[str]) -> int:
        """Load the module rooted in this file, answering its number."""
        real = os.path.realpath(root)
        if real in by_path:
            return by_path[real]
        if real in being:
            ring = " imports ".join(being + [root])
            raise import_error(f"these modules import one another: {ring}")

        nonlocal lines
        text, starts, read_paths = read_program([root], paths_asked)
        m = Module(len(mods), root)
        m.text = text
        m.paths = read_paths
        m.starts = [st + lines for st in starts]
        by_path[real] = m.index
        mods.append(m)

        # what the module's text lands on in the one text every
        # diagnostic points into
        shift = lines
        pieces.append(text)
        all_starts.extend(m.starts)
        all_paths.extend(read_paths)
        lines += text.count("\n")

        if note_source is not None:
            note_source("".join(pieces), root, list(all_starts),
                        list(all_paths))
        toks = process_indentation(tokenize(text))
        for t in toks:
            t.line += shift
        m.defs = Parser(toks).parse()

        # What it binds, resolved and loaded in turn.  A binding is a
        # top-level let of an @import and nothing else; the value is
        # never evaluated, since a module is not a thing a program
        # holds.
        for d in m.defs:
            if isinstance(d, VarDef) and isinstance(d.init_expr, ImportExpr):
                # beside the file that asked, which is not always the
                # file the module is rooted in
                asked_in = file_at(m, d.pos[0]) if getattr(d, "pos", None) \
                    else root
                here = resolve(d.init_expr.name, os.path.dirname(asked_in),
                               paths_asked, asked_in)
                m.bindings[d.name] = take(here, root, being + [real])
        return m.index

    for r in roots:
        take(r, None, [])
    return mods, "".join(pieces), all_starts, all_paths


# ---------------------------------------------------------------------------
# Two problems, two tools
# ---------------------------------------------------------------------------
#
# A module's names have to be told from another module's, and there are
# two kinds of name to tell apart.
#
# A **value** name -- what a call or a variable reference spells -- may
# be shadowed by a local binding, and which one is meant is not known
# until the innermost frame has been asked.  So value names are left as
# written and settled where they are looked up: the module's own key
# first, then what is nobody's, which is the builtins and std.
#
# A **type** name cannot be shadowed by a local, so nothing is learned
# by waiting: type names are rewritten where the module is loaded, and
# everything downstream sees a name that is already the right one.
#
# The root module takes no prefix, so a program that binds no import is
# keyed exactly as it was before any of this and pays nothing for it.


def type_names_of(defs) -> set:
    """The types a module defines: structs, enums, sums and aliases."""
    from interp.ast import StructDef, EnumDef, TypeDef, SumTypeDef
    out = set()
    for d in defs:
        if isinstance(d, (StructDef, EnumDef, TypeDef, SumTypeDef)):
            out.add(d.name)
    return out


def rename_types(defs, mine: set, qualify, through=None) -> None:
    """Rewrite every type name a module writes into the key it is under.

    Two kinds are rewritten: a name the module defines itself, which
    takes its own key, and `m.Name` where m is a bound import, which
    takes that module's.  Everything else -- a builtin, a type variable
    -- is somebody else's business and is left as written.
    """
    seen: set[int] = set()
    through = through or {}

    def fix(t):
        if not isinstance(t, str):
            return t
        if t in mine:
            return qualify(t)
        head, dot, rest = t.partition(".")
        if dot and head in through:
            target = through[head]
            if rest not in target.exports:
                raise KeyError(
                    f"the module {target.root} does not let others name "
                    f"'{rest}'; @export says what leaves a module")
            return target.qualify(rest)
        return t

    def walk(node):
        if node is None or isinstance(node, (str, int, float, bool)):
            return
        if id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, (list, tuple)):
            for x in node:
                walk(x)
            return
        if isinstance(node, dict):
            for x in node.values():
                walk(x)
            return
        for attr in _TYPE_NAME_BY_CLASS.get(type(node).__name__, ()):
            if hasattr(node, attr):
                setattr(node, attr, fix(getattr(node, attr)))
        slots = getattr(node, "__slots__", None)
        names = slots if slots is not None else getattr(node, "__dict__", {})
        for attr in list(names):
            try:
                v = getattr(node, attr)
            except AttributeError:
                continue
            if attr in _TYPE_ATTRS:
                if isinstance(v, list):
                    setattr(node, attr, [fix(x) for x in v])
                else:
                    setattr(node, attr, fix(v))
                continue
            if attr in _NAMED_TYPE_PAIRS and isinstance(v, list):
                # a parameter and a field are each a name and a type,
                # and it is the type that is one of ours
                setattr(node, attr,
                        [(pair[0], fix(pair[1])) + tuple(pair[2:])
                         if isinstance(pair, tuple) and len(pair) >= 2
                         else pair
                         for pair in v])
                continue
            walk(v)

    for d in defs:
        walk(d)


# Where a type is written down rather than computed.  A name in one of
# these is a type's name and nothing else, which is what makes
# rewriting it safe.
_TYPE_ATTRS = frozenset({
    "type_annotation", "ret_type", "return_type", "field_types",
    "param_types", "target_type", "element_type", "underlying", "target",
    "type_name", "struct_name",
})

# Where a list holds a name and a type together: a function's
# parameters and a struct's fields.
_NAMED_TYPE_PAIRS = frozenset({"params", "fields"})

# Nodes whose plain `name` is a type's rather than a value's or a
# function's.  A struct literal writes the type it makes.
_TYPE_NAME_BY_CLASS = {
    "StructLit": ("name",),
}


class ModuleHandle:
    """What a bound import is worth: a way into one module and no more.

    A module is not a thing a program holds -- it cannot be passed,
    stored, compared or answered -- so every use of one but reaching
    into it with `.` is refused where it is written.  What the handle
    carries is the key its module's names are under and what that
    module lets others name.
    """

    __slots__ = ("prefix", "exports", "where")

    def __init__(self, prefix: str, exports: set, where: str):
        self.prefix = prefix
        self.exports = exports
        # the file it was bound from, for a diagnostic to name
        self.where = where

    def key(self, name: str) -> str:
        return f"{self.prefix}.{name}" if self.prefix else name

    def display(self) -> str:
        return f"the module {self.where}"


def prepare(mods):
    """Make one definition list of the modules, each name under its key.

    Every module but the root one has its types renamed and its
    definitions stamped with the key its names live under; a bound
    import is given the handle it is worth, so that installing one is a
    binding and not an evaluation.  What comes back is what the
    installer has always been handed: one list, in order.
    """
    from interp.ast import (ImportExpr, VarDef, StructDef, EnumDef,
                            TypeDef, SumTypeDef)

    for m in mods:
        m.exports = {d.name for d in m.defs
                     if getattr(d, "is_export", False)}

    out = []
    for m in mods:
        through = {name: mods[k] for name, k in m.bindings.items()}
        if m.prefix or through:
            mine = type_names_of(m.defs)
            rename_types(m.defs, mine, m.qualify, through)
        if m.prefix:
            for d in m.defs:
                if isinstance(d, (StructDef, EnumDef, TypeDef, SumTypeDef)):
                    d.name = m.qualify(d.name)
        for d in m.defs:
            # a module line inside a file still sections it, and the
            # module the file is stays outside that
            own = getattr(d, "module", "")
            if m.prefix:
                d.module = f"{m.prefix}.{own}" if own else m.prefix
            if isinstance(d, VarDef) and isinstance(d.init_expr, ImportExpr):
                target = mods[m.bindings[d.name]]
                d.import_handle = ModuleHandle(
                    target.prefix, target.exports, target.root)
        out.extend(m.defs)
    return out
