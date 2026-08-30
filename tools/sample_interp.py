"""A 2 ms stack sampler around the interpreter's main: leaf and stack tallies."""
import collections, os, runpy, sys, threading, time
sys.path.insert(0, os.getcwd())
leaf = collections.Counter(); under = collections.Counter(); n = [0]
# which mechanism a sample is under first, walking up from the leaf:
# the nearest of these names says whose cost the sample is
mech = collections.Counter()
MECH = {"block": "body", "eval_stmts": "body",
        "_call_user_func_inner": "call", "_call_user_func": "call",
        "_end_scope": "call", "_check_return_type": "call",
        "_check_borrowed_answer": "call", "_check_conditions": "call",
        "_wrap_optional_return": "call",
        "_call_method": "dispatch", "_do_call": "dispatch", "_call_func": "dispatch",
        "_c_call": "dispatch", "_c_method": "dispatch",
        "_c_foreach_setup": "foreach", "_c_foreach_run": "foreach",
        "_resolve_iterable": "foreach", "_run_loop_body": "loop",
        "_c_vardef_bind": "let", "_c_vardef_pre": "let", "_es_VarDef": "let",
        "_c_assign_post": "assign", "_c_assign_pre": "assign",
        "_apply_operator": "operator", "_c_getattr": "getattr",
        "_c_sub_index": "subscript", "eval_expr": "walk"}
main_id = threading.get_ident()
def dump():
    out = open(os.environ.get("SAMPLE_OUT", "/dev/stderr"), "w")
    print(f"wall {time.time()-t0:.1f}s, {n[0]} samples", file=out)
    print("--- leaf (file, function, line) ---", file=out)
    for k, v in leaf.most_common(40): print(f"{100*v/max(n[0],1):5.1f}% {k}", file=out)
    print("--- mechanism the sample is under first ---", file=out)
    for k, v in mech.most_common(): print(f"{100*v/max(n[0],1):5.1f}% {k}", file=out)
    print("--- under (file, function) ---", file=out)
    for k, v in under.most_common(40): print(f"{100*v/max(n[0],1):5.1f}% {k}", file=out)
    out.close()
def sampler():
    last = time.time()
    while True:
        time.sleep(0.002)
        if time.time() - last > 30:
            dump(); last = time.time()
        f = sys._current_frames().get(main_id)
        if f is None: continue
        n[0] += 1
        leaf[(f.f_code.co_filename.split("/")[-1], f.f_code.co_name, f.f_lineno)] += 1
        g = f; m = "other"
        while g is not None:
            k = MECH.get(g.f_code.co_name)
            if k is not None:
                m = k; break
            g = g.f_back
        mech[m] += 1
        seen = set()
        while f is not None:
            k = (f.f_code.co_filename.split("/")[-1], f.f_code.co_name)
            if k not in seen:
                seen.add(k); under[k] += 1
            f = f.f_back
sys.argv = ["interp"] + sys.argv[1:]
t0 = time.time()
threading.Thread(target=sampler, daemon=True).start()
try:
    runpy.run_module("interp", run_name="__main__", alter_sys=True)
except SystemExit:
    pass
finally:
    dump()
