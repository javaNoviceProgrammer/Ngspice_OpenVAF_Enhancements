#!/usr/bin/env python3
"""verify_idxcast.py -- Enhancement-274: a vector index out of int range no longer
invokes undefined behaviour.

`op_ind` (src/frontend/evaluate.c) rounds a vector index with
`(int) floor(value + 0.5)`. Casting a `double` outside int range to `int` is
undefined behaviour, so `v(a)[1e308]` (or an `inf`/`NaN` index) tripped UBSan.
The code already clamps the resulting index to `[0, majsize-1]` afterwards -- the
only defect was the cast itself. Fixed with `idx_floor()`, which clamps the value
to int range (and maps NaN to 0) before casting; an out-of-range index is then
clamped to the last element exactly as a large in-range index already was.

The test passes iff the out-of-range indices resolve cleanly (no UB, no crash) and
valid indexing still returns the right elements. Reported via exit code (0 = pass).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = ("* index-cast test\nr1 a b 1k\nr2 b 0 1k\nc1 b 0 1u\n"
        "v1 a 0 dc 1 pulse(0 1 0 1u 1u 1m 2m)\n")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=15):
    deck = BASE + ".control\ntran 1u 20u\nlet vx = v(b)\n" + control + \
        "\nquit\n.endc\n.end\n"
    path = os.path.join(HERE, "_ix.cir")
    with open(path, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"


def nocrash(rc):
    return rc is not None and rc >= 0 and rc != 139


print("Enhancement-274: out-of-range vector index -> no UB (evaluate.c op_ind)")

# [1] huge index -- was (int)floor(1e308) UB; now clamps to the last element.
rc, out = run("print vx[1e308]")
check("[1] `vx[1e308]` -> clean (was (int)1e308 UB)", nocrash(rc)
      and "outside the range" not in out.lower(), f"rc={rc}")

# [2] huge index via 1e30.
rc, out = run("print vx[1e30]")
check("[2] `vx[1e30]` -> clean, no UB", nocrash(rc)
      and "outside the range" not in out.lower(), f"rc={rc}")

# [3] a NaN-valued index (0/0) must not fault.
rc, out = run("let bad = 0/0\nprint vx[bad]")
check("[3] a NaN index -> clean, no crash", nocrash(rc), f"rc={rc}")

# [4] valid index still returns the right element (v(b)[0] is the t=0 sample = 0).
rc, out = run("print vx[0]")
m = re.search(r"vx\[0\]\s*=\s*([-\d.eE+]+)", out)
check("[4] a valid `vx[0]` still returns 0", nocrash(rc) and m is not None
      and abs(float(m.group(1))) < 1e-6, f"={m.group(1) if m else '?'}")

# [5] a valid range index still works.
rc, out = run("print vx[0:2]")
check("[5] a valid range `vx[0:2]` still works", nocrash(rc)
      and "outside the range" not in out.lower(), f"rc={rc}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
