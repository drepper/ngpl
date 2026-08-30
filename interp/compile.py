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
    ReturnStmt, Subscript, UnitExpr, VarRef,
)

# NGPLI_INTERPRET=1 turns compilation off, for an A/B against the walk.
ENABLED = os.environ.get("NGPLI_INTERPRET", "") == ""

# operators the evaluator's _apply_operator takes as they are; the
# three that short-circuit or unwrap are left to the handler
_PLAIN_BINOPS = None  # settled lazily: everything but ??, and, or


class _Emit:
    """The source of one block, and the constants it refers to."""

    def __init__(self, ev, stmts):
        self.ev = ev
        self.stmts = stmts
        self.k: list[Any] = []
        self.lines: list[str] = []

    def const(self, value) -> str:
        self.k.append(value)
        return f"K[{len(self.k) - 1}]"

    def line(self, depth: int, text: str) -> None:
        self.lines.append("    " * depth + text)

    # ---- expressions ---------------------------------------------------

    def expr(self, node, observable: bool = True) -> str:
        """A Python expression evaluating this node to a Value.

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
            # what _ee_IntLit boxes, boxed once here instead
            k = self.const(self.ev._ee_IntLit(node))
            if observable and node.pos is not None:
                return f"ev._c_at({self.const(node.pos)}, {k})"
            return k
        if cls is VarRef:
            if node.name == DISCARD_NAME:
                return f"ev._c_var({self.const(node)})"
            return f"ev._c_var2({self.const(node.name)}, {self.const(node.pos)})"
        if cls is BinOp and node.op not in ("??", "and", "or"):
            # the integer handler for this operator, found once here
            # rather than at every evaluation; None where there is none
            h = self.ev._ops.get(node.op)
            if h is not None:
                return (f"ev._c_iop({self.expr(node.left, False)}, "
                        f"{self.expr(node.right, False)}, {self.const(h)}, "
                        f"{self.const(node.op)}, {self.const(node.pos)})")
            return (f"ev._c_binop({self.expr(node.left, False)}, "
                    f"{self.expr(node.right, False)}, {self.const(node.op)}, "
                    f"{self.const(node.pos)})")
        if cls is FuncCall:
            n = len(node.args)
            args = ", ".join(self.expr(a, i == n - 1) for i, a in enumerate(node.args))
            # the call's own position first, as the walk writes it on
            # entering the node, and the arguments after it in order
            return (f"ev._c_call({self.const(node)}, "
                    f"ev._c_pos({self.const(node.pos)}) and [{args}])")
        if cls is GetAttr:
            return (f"ev._c_getattr({self.const(node)}, "
                    f"ev._c_pos({self.const(node.pos)}) and {self.expr(node.obj)})")
        if cls is UnitExpr:
            from interp.units import eval_unit_formula
            unit = self.const(eval_unit_formula(node.unit_spec))
            return (f"ev._c_unit(ev._c_pos({self.const(node.pos)}) and "
                    f"{self.expr(node.expr)}, {unit})")
        if cls is Subscript and len(node.indices) == 1 and node.indices[0] is not None:
            # a subscript that spells a type is settled before anything
            # is read, so it is asked first and answers instead
            return (f"(ev._c_sub_start({self.const(node)}) or "
                    f"ev._c_sub_index(ev._c_sub_before({self.expr(node.obj, False)}), "
                    f"{self.expr(node.indices[0])}))")
        if cls is MethodCall and not E.MODULES:
            n = len(node.args)
            args = ", ".join(self.expr(a, i == n - 1) for i, a in enumerate(node.args))
            return (f"ev._c_method({self.const(node)}, "
                    f"ev._c_pre_method({self.const(node)}) and "
                    f"{self.expr(node.obj, n == 0)}, [{args}])")
        return f"ev.eval_expr({self.const(node)})"

    # ---- statements ----------------------------------------------------

    def stmt(self, i: int, stmt, is_last: bool, info) -> None:
        d = 2  # inside the try of the statement's temporaries scope
        n = self.const(stmt)
        pos = getattr(stmt, "pos", None) if not isinstance(stmt, tuple) else None
        self.line(1, "if E._watchdog_armed: ev._watchdog_tick()")
        if pos is not None:
            p = self.const(pos)
            self.line(1, f"ev._last_pos = {p}")
            self.line(1, f"if cs: cs[-1][1] = {p}")
        self.line(1, "outer = ev._temporaries")
        self.line(1, "ev._temporaries = _NO_TEMPS")
        self.line(1, "try:")
        cls = stmt.__class__
        if cls is ExprStmt:
            self.line(d, f"result = {self.expr(stmt.expr)}")
        elif cls is ReturnStmt:
            if stmt.value is not None:
                self.line(d, f"raise _ReturnSentinel({self.expr(stmt.value)})")
            else:
                self.line(d, "raise _ReturnSentinel(none())")
        elif cls is IfStmt:
            self.line(d, f"if to_bool({self.expr(stmt.cond)}):")
            self.line(d + 1, f"result = ev.eval_stmts({self.const(stmt.cons)})")
            alt = stmt.alt
            closed = False
            while alt is not None:
                alt_cond, alt_body, *rest = alt
                if alt_cond is None:
                    self.line(d, "else:")
                    self.line(d + 1, f"result = ev.eval_stmts({self.const(alt_body)})")
                    closed = True
                    break
                self.line(d, f"elif to_bool({self.expr(alt_cond)}):")
                self.line(d + 1, f"result = ev.eval_stmts({self.const(alt_body)})")
                alt = rest[0] if rest else None
            if not closed:
                self.line(d, "else:")
                self.line(d + 1, "result = none()")
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
            self.stmt(i, s, i == last, info)
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
            "LambdaValue": V.LambdaValue,
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
