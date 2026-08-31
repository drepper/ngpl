"""Compile a block of statements to Python source, once, and run that.

The evaluator walks the tree: every statement and every expression is
a dispatch on the node's class, a position written down, a handler
frame entered.  Measured on the compiler compiling itself that
walking is a third of the whole run, spread thin -- there is no hot
spot, only the cost of being a tree-walker.

So each block is turned into a Python function the first time it
runs.  The function does exactly what the walk did, statement by
statement -- the same bookkeeping in the same order, calling the same
handlers -- except that what is known at compile time is written
down rather than found again: which handler a statement wants, where
a position is, whether a statement is the last use of a name.  What
this file does not know how to compile it hands to the evaluator, node
by node, so the whole program runs compiled from the first statement
and coverage grows without a cliff.

The source is in statement form: an expression becomes a run of
assignments to temporaries, in the order the walk evaluates its
parts, and the value ends in the last temporary.  That is what lets a
position be written as two stores rather than a call, a variable read
be a dictionary probe rather than a handler, and a loop be a loop.

The evaluator remains the definition.  A compiled block that says
anything the walk would not is a bug here, and the gate is that the
compiler compiled under the two is the same binary, byte for byte.
"""

from __future__ import annotations

import os
from typing import Any

from interp.value import DISCARD_NAME
from interp.ast import (
    BinOp, ExprStmt, FuncCall, GetAttr, IfStmt, IntLit, MethodCall,
    ForEachStmt, ReturnStmt, Subscript, UnitExpr, VarDef, VarRef, WhileStmt,
)

# NGPLI_INTERPRET=1 turns compilation off, for an A/B against the walk.
ENABLED = os.environ.get("NGPLI_INTERPRET", "") == ""


class _Emit:
    """The source of one block, and the constants it refers to."""

    def __init__(self, ev, stmts):
        self.ev = ev
        self.stmts = stmts
        self.k: list[Any] = []
        self.lines: list[str] = []
        self.ntemp = 0

    def const(self, value) -> str:
        self.k.append(value)
        return f"K[{len(self.k) - 1}]"

    def line(self, depth: int, text: str) -> None:
        self.lines.append("    " * depth + text)

    def temp(self) -> str:
        self.ntemp += 1
        return f"t{self.ntemp}"

    def pos(self, d: int, pos) -> None:
        """What the walk writes on entering a node."""
        if pos is not None:
            p = self.const(pos)
            self.line(d, f"ev._last_pos = {p}")
            self.line(d, f"if cs: cs[-1][1] = {p}")

    # ---- expressions ---------------------------------------------------

    def expr(self, d: int, node, observable: bool = True) -> str:
        """Emit statements evaluating this node; answer the temporary
        holding its value.

        The walk writes every node's position down as it enters it, and
        what a backtrace or a diagnostic then shows is the position of
        the last node entered.  A node that cannot fail still has to
        write its position when that could be the last one written --
        the last argument of a call, say -- and need not when whatever
        follows writes its own first; `observable` is the caller saying
        which.  A binary operator writes its own position again after
        its operands, so under one nothing an operand writes is seen.
        """
        cls = node.__class__
        if cls is IntLit:
            k = self.const(self.ev._ee_IntLit(node))
            if observable:
                self.pos(d, node.pos)
            return k
        if cls is VarRef and node.name != DISCARD_NAME:
            # _ee_VarRef, with the innermost frame probed here: a name
            # it holds is what lookup would have answered first
            self.pos(d, node.pos)
            nm = self.const(node.name)
            t = self.temp()
            # the frozen table is probed once, and only the two states
            # that refuse a read go to the helper; the purity question
            # is only asked of a name the innermost frame lacks, since
            # a name it has passes it whatever the answer would be
            self.line(d, f"{t} = ev._frozen_vars.get({nm})")
            self.line(d, f"if {t} is MOVED or {t} is LENT_MUT: ev._c_frozen_refuse({nm}, {t})")
            self.line(d, f"{t} = ev.env._frames[-1].get({nm}, M)")
            self.line(d, f"if {t} is M:")
            self.line(d + 1, f"if ev._pure_func_name is not None: ev._c_pure_check({nm})")
            self.line(d + 1, f"{t} = ev._c_lookup({nm})")
            self.line(d, f"if isinstance({t}, Reference): {t} = {t}.get()")
            return t
        if cls is BinOp and node.op in ("and", "or"):
            # the walk's short circuit: the right side is not read when
            # the left already answers, and both are held to be truth
            # values
            self.pos(d, node.pos)
            a = self.expr(d, node.left, False)
            t = self.temp()
            self.line(d, f"{t} = ev._logic_bool(_unwrap_operand({a}))")
            self.line(d, f"if {'not ' if node.op == 'and' else ''}{t}:")
            self.line(d + 1, f"{t} = mk_bool({node.op == 'or'})")
            self.line(d, "else:")
            b = self.expr(d + 1, node.right, False)
            self.pos(d + 1, node.pos)
            self.line(d + 1, f"{t} = mk_bool(ev._logic_bool(_unwrap_operand({b})))")
            return t
        if cls is BinOp and node.op not in ("??", "and", "or"):
            self.pos(d, node.pos)
            a = self.expr(d, node.left, False)
            b = self.expr(d, node.right, False)
            self.pos(d, node.pos)
            t = self.temp()
            h = self.ev._ops.get(node.op)
            op = self.const(node.op)
            if h is not None:
                hk = self.const(h)
                self.line(d, f"if type({a}) is IntValue and type({b}) is IntValue: {t} = {hk}({a}, {b})")
                self.line(d, f"else: {t} = ev._apply_operator({op}, {a}, {b})")
            else:
                self.line(d, f"{t} = ev._apply_operator({op}, {a}, {b})")
            return t
        if cls is FuncCall:
            self.pos(d, node.pos)
            n = len(node.args)
            args = [self.expr(d, a, i == n - 1) for i, a in enumerate(node.args)]
            t = self.temp()
            self.line(d, f"{t} = ev._c_call({self.const(node)}, [{', '.join(args)}])")
            return t
        if cls is GetAttr:
            self.pos(d, node.pos)
            if _into_module(self.ev, node):
                # a name read out of a module, which the walk takes
                # another way
                t = self.temp()
                self.line(d, f"{t} = ev.eval_expr({self.const(node)})")
                return t
            o = self.expr(d, node.obj)
            t = self.temp()
            self.line(d, f"{t} = ev._c_getattr({self.const(node)}, {o})")
            return t
        if cls is UnitExpr:
            from interp.units import eval_unit_formula
            self.pos(d, node.pos)
            v = self.expr(d, node.expr)
            t = self.temp()
            self.line(d, f"{t} = ev._c_unit({v}, {self.const(eval_unit_formula(node.unit_spec))})")
            return t
        if cls is Subscript and len(node.indices) == 1 and node.indices[0] is not None:
            # a subscript that spells a type is settled before anything
            # is read, so it is asked first and answers instead
            t = self.temp()
            self.line(d, f"{t} = ev._c_sub_start({self.const(node)})")
            self.line(d, f"if {t} is None:")
            o = self.expr(d + 1, node.obj, False)
            self.line(d + 1, f"{o} = ev._c_sub_before({o})")
            i = self.expr(d + 1, node.indices[0])
            self.line(d + 1, f"{t} = ev._c_sub_index({o}, {i})")
            return t
        if cls is MethodCall and not _into_module(self.ev, node):
            # a call into a module is the one the walk takes another
            # way, and which it is is a matter of the node alone
            n = len(node.args)
            self.line(d, f"ev._c_pre_method({self.const(node)})")
            o = self.expr(d, node.obj, n == 0)
            args = [self.expr(d, a, i == n - 1) for i, a in enumerate(node.args)]
            t = self.temp()
            self.line(d, f"{t} = ev._c_method({self.const(node)}, {o}, [{', '.join(args)}])")
            return t
        t = self.temp()
        self.line(d, f"{t} = ev.eval_expr({self.const(node)})")
        return t

    # ---- statements ----------------------------------------------------

    def stmt(self, stmt, is_last: bool, info) -> None:
        d = 2  # inside the try of the statement's temporaries scope
        n = self.const(stmt)
        pos = getattr(stmt, "pos", None) if not isinstance(stmt, tuple) else None
        self.line(1, "if E._watchdog_armed: ev._watchdog_tick()")
        self.pos(1, pos)
        self.line(1, "outer = ev._temporaries")
        self.line(1, "ev._temporaries = _NO_TEMPS")
        self.line(1, "try:")
        cls = stmt.__class__
        if cls is ExprStmt:
            v = self.expr(d, stmt.expr)
            self.line(d, f"result = {v}")
        elif cls is ReturnStmt:
            if stmt.value is not None:
                v = self.expr(d, stmt.value)
                self.line(d, f"raise _ReturnSentinel({v})")
            else:
                self.line(d, "raise _ReturnSentinel(none())")
        elif cls is IfStmt:
            c = self.expr(d, stmt.cond)
            self.line(d, f"if to_bool({c}):")
            self.line(d + 1, f"result = ev.eval_stmts({self.const(stmt.cons)})")
            alt = stmt.alt
            depth = d
            closed = False
            while alt is not None:
                alt_cond, alt_body, *rest = alt
                if alt_cond is None:
                    self.line(depth, "else:")
                    self.line(depth + 1, f"result = ev.eval_stmts({self.const(alt_body)})")
                    closed = True
                    break
                # an elif's condition is only read when the ones
                # before it were false, so it is emitted inside the else
                self.line(depth, "else:")
                depth += 1
                c2 = self.expr(depth, alt_cond)
                self.line(depth, f"if to_bool({c2}):")
                self.line(depth + 1, f"result = ev.eval_stmts({self.const(alt_body)})")
                alt = rest[0] if rest else None
            if not closed:
                self.line(depth, "else:")
                self.line(depth + 1, "result = none()")
        elif cls is VarDef:
            # _es_VarDef with the initializer evaluated here
            self.line(d, f"b = ev._c_vardef_pre({n})")
            if stmt.name == DISCARD_NAME:
                self.expr(d, stmt.init_expr)
                self.line(d, "result = none()")
            else:
                self.line(d, f"ev._c_vardef_frozen({n})")
                v = self.expr(d, stmt.init_expr)
                self.line(d, f"result = ev._c_vardef_bind({n}, {v}, b)")
        elif (cls is ForEachStmt and len(stmt.vars) == 1 and len(stmt.iterables) == 1
                and not isinstance(stmt.vars[0][0], tuple) and stmt.vars[0][1] is None):
            # _eval_foreach in its plain form -- one name, one sequence,
            # no type to coerce to -- with the turn of the loop inline
            nm = self.const(stmt.vars[0][0])
            self.line(d, f"st = ev._c_foreach_setup({n})")
            self.line(d, "if st is None: result = none()")
            self.line(d, "else:")
            self.line(d + 1, "seq = st[0][0]")
            self.line(d + 1, "try:")
            self.line(d + 2, "for idx in range(len(seq)):")
            self.line(d + 3, f"ev.env.define({nm}, seq[idx])")
            self.line(d + 3, f"if not ev._run_loop_body({self.const(stmt.body)}, {n}): break")
            self.line(d + 1, "finally:")
            self.line(d + 2, "ev._c_foreach_end(st[3])")
            self.line(d + 1, "result = none()")
        elif cls is WhileStmt and stmt.var_name is None:
            # _eval_while without a bound name: the condition inline,
            # the body a turn of _run_loop_body
            self.line(d, "while True:")
            c = self.expr(d + 1, stmt.cond)
            self.line(d + 1, f"if not to_bool({c}): break")
            self.line(d + 1, f"if not ev._run_loop_body({self.const(stmt.body)}, {n}): break")
            self.line(d, "result = none()")
        elif isinstance(stmt, tuple) and len(stmt) == 3 and stmt[0] == "assign_stmt":
            # the generalized assignment, its right side evaluated here
            target = self.const(stmt[1])
            self.line(d, f"pre = ev._c_assign_pre({target})")
            v = self.expr(d, stmt[2])
            self.line(d, f"result = ev._c_assign_post({target}, {v}, pre)")
        else:
            handler = E._STMT_DISPATCH.get(cls) if not isinstance(stmt, tuple) else None
            if handler is not None:
                self.line(d, f"result = {self.const(handler)}(ev, {n})")
            else:
                self.line(d, f"result = ev._eval_stmt({n})")
        # what eval_stmt does around a statement, and eval_stmts after it
        self.line(d, "if ev._temporaries: ev._release_temporaries(result)")
        self.line(1, "except BaseException:")
        self.line(d, "if ev._temporaries: ev._release_temporaries(None)")
        self.line(d, "raise")
        self.line(1, "finally:")
        self.line(d, "ev._temporaries = outer")
        self.line(d, "ev._pending_lend = None")
        self.line(1, "if isinstance(result, _ReturnSentinel): raise result")
        if not is_last and cls is ExprStmt:
            self.line(1, "if isinstance(result, LambdaValue): ev._warn_discarded_lambda(result)")
        # _after_last_use, with what it would find out settled now
        self.line(1, f"if ev._lend_ends: ev._c_end_lends({self.const(id(stmt))})")
        ending = [name for name in info["defs"]
                  if info["last"].get(name) is stmt and name not in info["escapes"]]
        if ending:
            self.line(1, f"ev._c_end_lives({self.const(tuple(ending))})")

    def block(self) -> str:
        stmts = self.stmts
        info = self.ev._block_info(stmts)
        self.line(0, "def block(ev, K):")
        self.line(1, "cs = ev._call_stack")
        self.line(1, "result = none()")
        last = len(stmts) - 1
        for i, s in enumerate(stmts):
            self.stmt(s, i == last, info)
        self.line(1, "return result")
        return "\n".join(self.lines) + "\n"


_NAMES = None


def _namespace():
    global _NAMES
    if _NAMES is None:
        from interp import value as V
        _NAMES = {
            "E": E, "none": V.none, "to_bool": E.to_bool,
            "_NO_TEMPS": E._NO_TEMPS, "_ReturnSentinel": E._ReturnSentinel,
            "LambdaValue": V.LambdaValue, "IntValue": V.IntValue,
            "Reference": V.Reference, "M": E._MISSING,
            "MOVED": E.Held.moved, "LENT_MUT": E.Held.lent_mut,
            "_unwrap_operand": E._unwrap_operand, "mk_bool": V.mk_bool,
        }
    return _NAMES


def compile_block(ev, stmts):
    """The block as a callable of the evaluator, or None where it
    could not be compiled -- which is then the walk's to run."""
    if not stmts:
        return None
    em = _Emit(ev, stmts)
    src = em.block()
    code = compile(src, f"<block {id(stmts)}>", "exec")
    ns = dict(_namespace())
    exec(code, ns)
    fn = ns["block"]
    K = tuple(em.k)
    return lambda ev, fn=fn, K=K: fn(ev, K)


import interp.eval as E  # noqa: E402  (after the names above, which eval imports)


def _into_module(ev, node) -> bool:
    """Whether this call reaches into a module rather than onto a value.

    `m.f(…)` where m is a bound import does; it is the walk's to make,
    since what it looks up is a name and not a method.
    """
    return (type(node.obj) is VarRef
            and ev._module_binding(node.obj.name) is not None)
