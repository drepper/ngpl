"""Expanding macros over the parse tree.

A macro comes in two forms.  One is a list of rewrite rules, each
saying what the arguments have to look like and what the invocation is
replaced by.  The other is a function that runs while the program is
being installed, is handed the parse tree of each thing the invocation
was written with, and answers the tree that replaces it.

Both are expanded here, and everything but the step that decides what
one invocation becomes is shared: where expansion happens, what an
invocation may stand for, and the renaming that keeps a macro's own
names out of the caller's way.

Expansion runs after parsing and before anything is checked, so what
the rest of the interpreter sees is a program with no macros left in
it.  Parsing first is possible here and is not in C: the grammar is
context-free and an invocation is marked, so nothing has to be known
about a name to read the text around it.
"""

import copy

from interp import ast as _ast
from interp.value import SyntaxValue


# How many times an expansion may produce another one before the
# interpreter decides the macros do not settle.
MAX_DEPTH = 64

_POSITION_FIELDS = frozenset({"pos", "label_pos", "field_positions"})


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


def _subtrees(value):
    """Every tree directly inside a value, which may be a list or a tuple."""
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _subtrees(item)
    elif _is_node(value):
        yield value


# ----------------------------------------------------------------------
# Matching, for a macro written as rules
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
# Filling in, for a macro written as rules
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


# ----------------------------------------------------------------------
# Hygiene, for both
# ----------------------------------------------------------------------

_hygiene_counter = 0


def make_hygienic(tree, spliced: set):
    """Rename what a macro's own quotes bind, in place.

    A name a macro introduces belongs to the macro.  Renaming it to
    something no source file can spell means an argument that mentions
    the same name still reads the caller's, which is what hygiene is.

    `spliced` holds the trees that came from the caller by way of `$`.
    Those keep their names: they are the caller's code, and the macro
    does not get to rename it.
    """
    global _hygiene_counter
    bound: dict[str, str] = {}

    def collect(value):
        for node in _subtrees(value):
            if id(node) in spliced:
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
            if id(node) in spliced:
                continue
            if isinstance(node, (_ast.VarDef, _ast.VarRef)) \
                    and getattr(node, "name", None) in bound:
                node.name = bound[node.name]
            for name in _fields(node):
                rename(getattr(node, name, None))

    collect(tree)
    if bound:
        rename(tree)
    return tree


# ----------------------------------------------------------------------
# Expanding
# ----------------------------------------------------------------------

# Every macro defined so far.  A session installs one entry at a time,
# and a macro defined in one entry is there for the next, which is what
# a name defined at the prompt does generally.
REGISTRY: dict = {}

# The functions defined alongside them.  A name may be both -- a macro
# and a function are not in the same namespace -- and where it is, a
# call of it is a call of the function and nothing to complain about.
FUNCTIONS: set = set()


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


def collect(definitions) -> dict:
    """Add the macros a batch of definitions defines, and answer them all.

    Two of a name in one batch is a mistake; one that replaces an
    earlier entry is a redefinition, which a session is for.
    """
    seen: set[str] = set()
    for defn in definitions:
        if isinstance(defn, (_ast.MacroRulesDef, _ast.MacroFuncDef)):
            if defn.name in seen:
                raise MacroError(f"macro {defn.name} is defined twice",
                                 getattr(defn, "pos", None))
            seen.add(defn.name)
            REGISTRY[defn.name] = defn
        elif isinstance(defn, _ast.FuncDef):
            FUNCTIONS.add(defn.name)
    return REGISTRY


def expand(node, macros: dict, runner, depth: int = 0):
    """Replace every macro invocation in a tree with what it answers.

    An invocation is expanded before what is written inside it, so a
    macro is handed the argument as the caller wrote it; what comes out
    is expanded in turn, so a macro may write another one.
    """
    if isinstance(node, _ast.MacroCall):
        if depth >= MAX_DEPTH:
            raise MacroError(
                f"expanding {node.name} did not settle after {MAX_DEPTH} "
                f"rewrites; a macro writes something that reaches it again",
                getattr(node, "pos", None))
        written = _apply(macros, node, runner)
        if isinstance(written, _Spliced):
            return _Spliced(expand(written.body, macros, runner, depth + 1),
                            written.call)
        return expand(written, macros, runner, depth + 1)
    # A macro written the way a function is called is the mistake this
    # language's marked invocation exists to catch, so it is said in
    # those words rather than left to be an undefined name.
    if isinstance(node, _ast.FuncCall) and node.name in macros \
            and node.name not in FUNCTIONS:
        kind = ("is written as rules"
                if isinstance(macros[node.name], _ast.MacroRulesDef)
                else "is written as a function over the program's text")
        raise MacroError(
            f"{node.name} is a macro -- it {kind} -- so it is invoked as "
            f"{node.name}⟦ … ⟧ rather than called as {node.name}( … ); "
            f"what a macro is handed is written rather than worked out",
            getattr(node, "pos", None))
    # A macro on its own line writes what it says in place of the line.
    if isinstance(node, _ast.ExprStmt) \
            and isinstance(node.expr, _ast.MacroCall):
        written = expand(node.expr, macros, runner, depth)
        if isinstance(written, _Spliced):
            return written.body
        node.expr = written
        return node
    if isinstance(node, list):
        made = []
        for item in node:
            written = expand(item, macros, runner, depth)
            if isinstance(written, list) and not isinstance(item, list):
                made.extend(written)
            else:
                made.append(_one(written))
        return made
    if isinstance(node, tuple):
        return tuple(_one(expand(item, macros, runner, depth))
                     for item in node)
    if not _is_node(node):
        return node
    for name in _fields(node):
        setattr(node, name,
                _one(expand(getattr(node, name, None), macros, runner,
                            depth)))
    return node


def _one(written):
    """Refuse a macro that writes statements where a value is wanted."""
    if isinstance(written, _Spliced):
        raise MacroError(
            f"{written.call.name} writes statements, so it is written on a "
            f"line of its own rather than where a value is wanted",
            getattr(written.call, "pos", None))
    return written


def _apply(macros: dict, call, runner):
    """The tree one invocation is replaced by, whichever kind it is."""
    macro = macros.get(call.name)
    if macro is None:
        raise MacroError(
            f"no macro named {call.name} is defined; ⟦ … ⟧ "
            f"invokes a macro and ( … ) calls a function",
            getattr(call, "pos", None))
    if isinstance(macro, _ast.MacroRulesDef):
        return _apply_rules(macro, call)
    return _apply_func(macro, call, runner)


def _apply_rules(macro, call):
    """Rewrite an invocation by the first rule whose pattern matches."""
    for rule in macro.rules:
        if len(rule.patterns) != len(call.args):
            continue
        binds: dict = {}
        if all(_match(p, a, binds)
               for p, a in zip(rule.patterns, call.args)):
            # The template is renamed before the holes are filled, so
            # what the rule binds is renamed and what came from the
            # caller -- which is not in the template yet -- is not.
            template = make_hygienic(copy.deepcopy(rule.template), set())
            filled = _fill(template, binds)
            if isinstance(filled, list):
                return _Spliced(filled, call)
            return filled
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


def _apply_func(macro, call, runner):
    """Run one macro and answer the tree it wrote."""
    wanted = len(macro.func.params)
    if len(call.args) != wanted:
        raise MacroError(
            f"{macro.name} is written with {wanted} argument"
            f"{'' if wanted == 1 else 's'} and is invoked here with "
            f"{len(call.args)}", getattr(call, "pos", None))
    handed = [SyntaxValue(node=copy.deepcopy(a)) for a in call.args]
    spliced = {id(t) for a in handed for t in _every_tree(a.node)}
    answer = runner(macro, handed, call)
    if not isinstance(answer, SyntaxValue):
        raise MacroError(
            f"{macro.name} answers a piece of the program, and this one "
            f"answered {type(answer).__name__.replace('Value', '').lower()}",
            getattr(call, "pos", None))
    if answer.is_block:
        return _Spliced(make_hygienic(answer.body, spliced), call)
    return make_hygienic(answer.node, spliced)


def _every_tree(node):
    """Every tree at any depth under a node, the node included."""
    if node is None:
        return
    yield node
    for name in _fields(node):
        for child in _subtrees(getattr(node, name, None)):
            yield from _every_tree(child)


def expand_definitions(definitions, macros: dict, runner) -> None:
    """Expand every macro in every definition, in place.

    A macro definition is left alone: what it writes is decided when it
    runs, not now.
    """
    for defn in definitions:
        if isinstance(defn, (_ast.MacroRulesDef, _ast.MacroFuncDef)):
            continue
        expand(defn, macros, runner)
