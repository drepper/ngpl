"""A 2 ms stack sampler around the interpreter's main: leaf and stack tallies."""
import collections, os, runpy, sys, threading, time
sys.path.insert(0, os.getcwd())
leaf = collections.Counter(); under = collections.Counter(); n = [0]
main_id = threading.get_ident()
def dump():
    out = open(os.environ.get("SAMPLE_OUT", "/dev/stderr"), "w")
    print(f"wall {time.time()-t0:.1f}s, {n[0]} samples", file=out)
    print("--- leaf (file, function, line) ---", file=out)
    for k, v in leaf.most_common(40): print(f"{100*v/max(n[0],1):5.1f}% {k}", file=out)
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
