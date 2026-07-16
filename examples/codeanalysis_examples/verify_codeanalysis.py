#!/usr/bin/env python3
"""Enhancement-211: bug fixes from a static-analysis pass over the ngspice tree.

Two defects found with clang's static analyzer and confirmed by reading the code:

  [dcop/xspice] `DCop()` (spicelib/analysis/dcop.c) had a braceless `else` that
        originally guarded the analog `CKTop()` solve so it ran ONLY when there
        were no event-driven (XSPICE) instances. Enhancement-188 (DC warm-start)
        inserted code between the `else` and `CKTop`, so the `else` then covered
        only its first statement and `CKTop` ran unconditionally -- for a
        mixed-signal deck BOTH `EVTop` and `CKTop` ran (re-solving/overwriting the
        event-driven DC result), and `wsize` was read uninitialised on the EVTop
        path. Fixed by hoisting `wsize` before the branch and bracing the else.

  [ltspice-table] `inp_compat()` (frontend/inpcom.c) converts an LTSPICE
        `E ... table=(...)` source using an UNINITIALISED `char *ckt_array[100]`.
        The LTSPICE branch sets only ckt_array[1]; a single-pair table (ipairs==1)
        then `tfree(ckt_array[2])` -- a free of a garbage stack pointer. Fixed by
        zero-initialising the array so an unwritten slot's tfree() is a safe no-op.

These guards exercise the fixed paths and assert correct results (a would-fail
before/after test is impractical: the redundant CKTop leaves the simple-circuit DC
point unchanged, and freeing a garbage pointer is undefined behaviour that may or
may not crash). Run under BOTH linear solvers.

Every deck starts with a title line (SPICE treats line 1 as the title).
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
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def run(deck, name):
    p = os.path.join(HERE, name)
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=60)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr, r.returncode

def val(out, node):
    m = re.search(rf"{re.escape(node)}\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None

# ---- [dcop/xspice] mixed-signal DC operating point ----
# An analog divider (v(a) = 0.5) plus an adc_bridge, which is an event-driven
# (XSPICE) instance -> DCop takes the EVTop path. The DC point must be correct and
# the run must not crash; with the pre-fix braceless else, CKTop also ran here.
xsp = """* E-211 xspice mixed-signal dc op
V1 in 0 DC 1
R1 in a 1k
R2 a 0 1k
aconv [a] [dout] adc
.model adc adc_bridge(in_low=0.4 in_high=0.6)
.control
op
print v(a)
.endc
.end
"""
out, rc = run(xsp, "_xsp.cir")
va = val(out, "v(a)")
check("[dcop/xspice] mixed-signal DC op runs (event-driven EVTop path) without error",
      rc == 0 and "DC solution failed" not in out and "aborted" not in out.lower(),
      out.strip()[-160:])
check("[dcop/xspice] the analog node solves to the correct divider value v(a) = 0.5",
      va is not None and abs(va - 0.5) < 1e-6, f"v(a)={va}")

# ---- [ltspice-table] single-pair E-source table import ----
# A single (x0, y0) pair -> ipairs == 1 -> the branch that freed ckt_array[2]. The
# convention is that a single pair yields the constant y0, so v(out) == 3.
lt = """* E-211 ltspice single-pair E table
.control
set ngbehavior=ltpsa
.endc
V1 in 0 DC 1
E1 out 0 in 0 table=(0.5, 3)
Rl out 0 1k
.control
op
print v(out)
.endc
.end
"""
out, rc = run(lt, "_lt.cir")
vo = val(out, "v(out)")
check("[ltspice-table] single-pair `E ... table=(x,y)` imports without crashing",
      rc == 0 and "segmentation" not in out.lower() and "abort" not in out.lower(),
      out.strip()[-160:])
check("[ltspice-table] a single (x0, y0) pair yields the constant y0 (v(out) = 3)",
      vo is not None and abs(vo - 3.0) < 1e-6, f"v(out)={vo}")

# ---- regression guard: plain analog DC op is unchanged ----
an = """* E-211 plain analog dc op
V1 in 0 DC 1
R1 in out 1k
R2 out 0 1k
.control
op
print v(out)
.endc
.end
"""
out, rc = run(an, "_an.cir")
vo = val(out, "v(out)")
check("[regression] plain analog DC op still solves to 0.5 (no behavior change)",
      vo is not None and abs(vo - 0.5) < 1e-6, f"v(out)={vo}")

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
