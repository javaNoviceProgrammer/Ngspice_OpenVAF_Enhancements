#!/usr/bin/env python3
"""verify_arraynodeprint.py -- Enhancement-224: reference array/bus node
voltages in interactive/print expressions.

Array/bus nodes (Enhancement-221) are named with literal brackets, e.g. `a[0]`.
The frontend expression parser reads `a[0]` as index 0 of a vector named `a`, so
`print v(a[0])` / `print a[0]` silently failed even though the node exists and
simulates. E-224 adds a literal-node fallback in three frontend spots
(parse.c checkvalid, evaluate.c op_ind, evaluate.c apply_func's v() path): when
the base name does not resolve and a node named `a[0]` exists, that node vector
is used. Ordinary vector indexing (realvec[3]) is unaffected -- it only fires
when the base name is an unresolved zero-length placeholder.

Checks (solver-independent; a `.op` DC point):
  1. `print a[0]`             -> node a[0] voltage = 1 V
  2. `print v(a[0])`          -> 1 V   (the v()-function form)
  3. `print v(a[1])`          -> 3 V
  4. `print v(a[0])-v(a[1])`  -> -2 V  (array nodes inside an expression)
  5. `print @r1[i]`           -> -1 mA (the bus resistor's branch current)
  6. regression: normal vector indexing `unitvec(4)[2]` still = 1
  7. a genuinely-missing node `v(a[9])` stays a clean miss (no crash/value)

Every SPICE deck starts with a title line (SPICE treats line 1 as the title).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)   # verify under BOTH KLU and Sparse solvers

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))

def run(deck, name="_t.cir"):
    p = os.path.join(HERE, name)
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=60)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr, r.returncode

def scalar(out, name):
    """Return the float printed for `print <name> = <value>` (exact name)."""
    for line in out.splitlines():
        m = re.match(r"\s*" + re.escape(name) + r"\s*=\s*([-\d.eE+]+)\s*$", line)
        if m:
            return float(m.group(1))
    return None

deck = open(os.path.join(HERE, "arraynode_print.cir")).read()
out, rc = run(deck)

va0    = scalar(out, "a[0]")
vva0   = scalar(out, "v(a[0])")
vva1   = scalar(out, "v(a[1])")
vdiff  = scalar(out, "v(a[0])-v(a[1])")
ir1    = scalar(out, "@r1[i]")

print("Enhancement-224: array/bus node voltages in print expressions")
check("no crash running the deck", rc == 0 and "segmentation" not in out.lower(), f"rc={rc}")
check("print a[0]            = 1 V",  va0   is not None and abs(va0   - 1.0)    < 1e-9, f"{va0}")
check("print v(a[0])         = 1 V",  vva0  is not None and abs(vva0  - 1.0)    < 1e-9, f"{vva0}")
check("print v(a[1])         = 3 V",  vva1  is not None and abs(vva1  - 3.0)    < 1e-9, f"{vva1}")
check("print v(a[0])-v(a[1]) = -2 V", vdiff is not None and abs(vdiff + 2.0)    < 1e-9, f"{vdiff}")
check("print @r1[i]          = -1 mA (bus resistor branch current)",
      ir1 is not None and abs(ir1 + 1e-3) < 1e-9, f"{ir1}")

# regression: ordinary vector indexing still works, and a genuine miss is clean
reg = ("* reg\nV0 a[0] 0 1\nR1 a[0] 0 1k\n.op\n.control\nrun\n"
       "let vv = unitvec(4)\nprint vv[2]\nprint v(a[9])\n.endc\n.end\n")
rout, rrc = run(reg, "_reg.cir")
check("regression: normal vector index unitvec(4)[2] = 1",
      scalar(rout, "vv[2]") is not None and abs(scalar(rout, "vv[2]") - 1.0) < 1e-9,
      f"{scalar(rout, 'vv[2]')}")
check("genuinely-missing node v(a[9]) prints no value and does not crash",
      rrc == 0 and scalar(rout, "v(a[9])") is None and "segmentation" not in rout.lower())

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
