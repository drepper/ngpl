"""Expanding macros over the parse tree.

A macro is a set of rewrite rules.  Each rule says what the arguments
of an invocation have to look like and what the invocation is replaced
by, and both halves are ordinary expression trees with MetaVar standing
where a hole is written.

Expansion runs after parsing and before anything is checked, so what
the rest of the interpreter sees is a program with no macros left in
it.  Parsing first is possible here and is not in C: the grammar is
context-free and an invocation is marked, so nothing has to be known
about a name to read the text around it.
"""

import copy

from interp import ast as _ast


# How many times an expansion may produce another one before the
# interpreter decides the rules do not settle.  A macro that rewrites
# to itself is the usual way to reach this.
MAX_DEPTH = 64

# Fields that say where a node was written rather than what it is.
# Two trees are the same shape whatever their positions, so matching
# passes over these.
_POSITION_FIELDS = frozenset({"pos", "label_pos", "field_positions"})


class _Spliced:
    """Statements a macro wrote, on their way to the line they replace.

    Kept apart from a plain list so that statements arriving where a
    value is wanted are refused rather than quietly taken into whatever
    list they landed in -- an argument list is a list too.
    """

    __slots__ = ("body", "call")

    def __init__(self, body: list, call):
        self.body = body
        self.call = call


class MacroError(Exception):
    """A macro could not be expanded."""

    def __init__(self, message, pos=None):
        super().__init__(message)
        self.pos = pos
        if pos is not None:
            self.line, self.col, self.end_col = pos


def _fields(node) -> tuple[str, ...]:
    """The names of what a node holds, however the node stores them."""
    if hasattr(node, "__dict__"):
        names = tuple(vars(node))
    else:
        names = tuple(getattr(type(node), "__slots__", ()))
    return tuple(n for n in names if n not in _POSITION_FIELDS)


def _is_node(value) -> bool:
    """Whether a value is a piece of parse tree."""
    return type(value).__module__ == "interp.ast"


# ----------------------------------------------------------------------
# Matching
# ----------------------------------------------------------------------

def _match(pattern, node, binds: dict) -> bool:
    """Whether a pattern describes a tree, filling in the holes it names.

    A hole matches anything and remembers what it matched, so a name
    written twice in one pattern has to match the same thing twice --
    which is how a rule says two arguments are alike.
    """
    if isinstance(pattern, _ast.MetaVar):
        seen = binds.get(pattern.name)
        if seen is not None:
            return _alike(seen, node)
        binds[pattern.name] = node
        return True
    if type(pattern) is not type(node):
        return False
    for name in _fields(pattern):
        if not _match_field(getattr(pattern, name, None),
                            getattr(node, name, None), binds):
            return False
    return True


def _match_field(pattern, node, binds: dict) -> bool:
    """Match one field, which may hold a tree, a list of them, or a value."""
    if _is_node(pattern):
        return _is_node(node) and _match(pattern, node, binds)
    if isinstance(pattern, (list, tuple)):
        return (isinstance(node, (list, tuple))
                and len(pattern) == len(node)
                and all(_match_field(p, n, binds)
                        for p, n in zip(pattern, node)))
    return pattern == node


def _alike(a, b) -> bool:
    """Whether two trees are the same shape, wherever each was written."""
    return _match_field(a, b, _NoBinds())


class _NoBinds(dict):
    """A binding table that refuses to learn, for a plain comparison."""

    def __setitem__(self, key, value):
        raise MacroError("a hole cannot be compared")


# ----------------------------------------------------------------------
# Filling in
# ----------------------------------------------------------------------

def _fill(node, binds: dict):
    """Copy a template, putting what was matched into its holes.

    What fills a hole is the argument's own tree, positions and all, so
    an error inside it points at the code the caller wrote.  What comes
    from the template keeps the macro's positions, which is where that
    part of the program was in fact written.
    """
    if isinstance(node, _ast.MetaVar):
        seen = binds.get(node.name)
        if seen is None:
            raise MacroError(
                f"${node.name} is filled in but nothing of that name is "
                f"matched", getattr(node, "pos", None))
        return copy.deepcopy(seen)
    if isinstance(node, list):
        return [_fill(item, binds) for item in node]
    if isinstance(node, tuple):
        return tuple(_fill(item, binds) for item in node)
    if not _is_node(node):
        return node
    made = copy.copy(node)
    for name in _fields(node):
        setattr(made, name, _fill(getattr(node, name, None), binds))
    return made


_hygiene_counter = 0


def _make_hygienic(template):
    """Rename what the template binds, so it cannot shadow the caller's.

    A name a macro introduces belongs to the macro.  Renaming it to
    something no source file can spell means an argument that mentions
    the same name still reads the caller's, which is what hygiene is.
    """
    bound: dict[str, str] = {}

    def collect(value):
        for node in _subtrees(value):
            # A hole holds the caller's code, which the macro does not
            # get to rename.
            if isinstance(node, _ast.MetaVar):
                continue
            if isinstance(node, _ast.VarDef) and isinstance(node.name, str) \
                    and node.name not in bound:
                global _hygiene_counter
                _hygiene_counter += 1
                bound[node.name] = f"{node.name}#{_hygiene_counter}"
            for name in _fields(node):
                collect(getattr(node, name, None))

    def rename(value):
        for node in _subtrees(value):
            if isinstance(node, _ast.MetaVar):
                continue
            if isinstance(node, (_ast.VarDef, _ast.VarRef)) \
                    and getattr(node, "name", None) in bound:
                node.name = bound[node.name]
            for name in _fields(node):
                rename(getattr(node, name, None))

    collect(template)
    if not bound:
        return template
    renamed = copy.deepcopy(template)
    rename(renamed)
    return renamed


def _subtrees(value):
    """Every tree directly inside a value, which may be a list or a tuple."""
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _subtrees(item)
    elif _is_node(value):
        yield value


def _child_trees(node):
    """Every tree directly under a node."""
    for name in _fields(node):
        yield from _subtrees(getattr(node, name, None))


# ----------------------------------------------------------------------
# Expanding
# ----------------------------------------------------------------------

# Every macro defined so far.  A session installs one entry at a time,
# and a macro defined in one entry is there for the next, which is what
# a name defined at the prompt does generally.
REGISTRY: dict = {}


def collect(definitions) -> dict:
    """Add the macros a batch of definitions defines, and answer them all.

    Two of a name in one batch is a mistake; one that replaces an
    earlier entry is a redefinition, which a session is for.
    """
    seen: set[str] = set()
    for defn in definitions:
        if isinstance(defn, _ast.MacroDef):
            if defn.name in seen:
                raise MacroError(
                    f"macro {defn.name} is defined twice",
                    getattr(defn, "pos", None))
            seen.add(defn.name)
            REGISTRY[defn.name] = defn
    return REGISTRY


def expand(node, macros: dict, depth: int = 0):
    """Replace every macro invocation in a tree with what it says.

    An invocation is expanded before what is written inside it, so a
    macro is handed the argument as the caller wrote it; what comes out
    is expanded in turn, so a macro may rewrite to another one.

    A macro that writes statements answers a list, which the list it
    was written in takes into itself.  One that writes an expression
    answers a tree, and standing where a value is wanted is the only
    place it may.
    """
    if isinstance(node, _ast.MacroCall):
        if depth >= MAX_DEPTH:
            raise MacroError(
                f"expanding {node.name} did not settle after {MAX_DEPTH} "
                f"rewrites; a rule rewrites to something it matches",
                getattr(node, "pos", None))
        written = _apply(macros, node)
        if isinstance(written, _Spliced):
            return _Spliced(expand(written.body, macros, depth + 1),
                            written.call)
        return expand(written, macros, depth + 1)
    # A macro on its own line writes what it says in place of the line.
    if isinstance(node, _ast.ExprStmt) \
            and isinstance(node.expr, _ast.MacroCall):
        written = expand(node.expr, macros, depth)
        if isinstance(written, _Spliced):
            return written.body
        node.expr = written
        return node
    if isinstance(node, list):
        made = []
        for item in node:
            written = expand(item, macros, depth)
            if isinstance(written, list) and not isinstance(item, list):
                made.extend(written)
            else:
                made.append(_one(written, item))
        return made
    if isinstance(node, tuple):
        return tuple(_one(expand(item, macros, depth), item)
                     for item in node)
    if not _is_node(node):
        return node
    for name in _fields(node):
        setattr(node, name,
                _one(expand(getattr(node, name, None), macros, depth),
                     getattr(node, name, None)))
    return node


def _one(written, before):
    """Refuse a macro that writes statements where a value is wanted."""
    if isinstance(written, _Spliced):
        raise MacroError(
            f"{written.call.name} writes statements, so it is written on a "
            f"line of its own rather than where a value is wanted",
            getattr(written.call, "pos", None))
    return written


def _apply(macros: dict, call):
    """The tree one invocation is replaced by."""
    macro = macros.get(call.name)
    if macro is None:
        raise MacroError(
            f"no macro named {call.name} is defined; ⟦ … ⟧ "
            f"invokes a macro and ( … ) calls a function",
            getattr(call, "pos", None))
    for rule in macro.rules:
        if len(rule.patterns) != len(call.args):
            continue
        binds: dict = {}
        if all(_match(p, a, binds)
               for p, a in zip(rule.patterns, call.args)):
            written = _fill(_make_hygienic(rule.template), binds)
            if isinstance(written, list):
                return _Spliced(written, call)
            return written
    counts = sorted({len(r.patterns) for r in macro.rules})
    if len(call.args) not in counts:
        wanted = " or ".join(str(c) for c in counts)
        raise MacroError(
            f"{macro.name} has rules for {wanted} argument"
            f"{'' if counts == [1] else 's'} and is written here with "
            f"{len(call.args)}", getattr(call, "pos", None))
    raise MacroError(
        f"no rule of {macro.name} matches what it is written with here",
        getattr(call, "pos", None))


def expand_definitions(definitions, macros: dict) -> None:
    """Expand every macro in every definition, in place.

    A macro definition is left alone: its rules are what expansion
    reads, not something to expand.
    """
    for defn in definitions:
        if isinstance(defn, _ast.MacroDef):
            continue
        expand(defn, macros)
