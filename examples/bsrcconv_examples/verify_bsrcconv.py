#!/usr/bin/env python3
"""Enhancement-256: no more SILENT spurious DC operating point for behavioral
sources whose derivative is singular at the v=0 initial guess.

A behavioral (B) source like `I=sqrt(v(n))` has an INFINITE small-signal
conductance dI/dv = 0.5/sqrt(v) at ngspice's default v=0 initial guess. That huge
Jacobian entry pins the node at v~0, so Newton takes a vanishing step and the
delta-V convergence test (which sees no change) declares "converged" -- at a point
that grossly VIOLATES KCL (the resistor pushes a full current into the node while
the source sinks ~0). ngspice silently reported this wrong operating point, and
gmin/source stepping never ran because the false convergence pre-empted them.

The fix (niiter.c) verifies the KCL residual after the delta-V test: if the worst
node-current imbalance is >100x the current-convergence tolerance, the point is
spurious -- decline it so CKTop falls through to gmin/source stepping, which
regularizes the singular node and finds the TRUE operating point. Result-neutral
for every well-behaved circuit (their residual sits ~1e-5, far under the
threshold). A companion guard (ptfuncs.c) stops `pwr(0, negative)` returning raw
+inf (like the existing /0 and sqrt(neg) guards), so a singular derivative stays
finite rather than poisoning the Jacobian with NaN.

Checks (both solvers):
 [1] `I=sqrt(v(n))` DC op == the analytic solution (v0=0.178045), KCL satisfied
     (i_B1 == i_R1), NOT the spurious v~0;
 [2] `I=0.1/v(n)` DC op == the analytic upper-branch solution (v0=0.887298);
 [3] the fix is result-neutral: finite-derivative B-sources (v^2, exp, v^3, tanh)
     converge to their exact operating points, unchanged.

Line 1 of every deck is the title (ignored).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    passed += 1 if ok else 0
    failed += 0 if ok else 1


def op(deck):
    open(os.path.join(HERE, "_b.cir"), "w").write(deck)
    out = subprocess.run([NGSPICE, "-b", "_b.cir"], capture_output=True, text=True,
                         cwd=HERE, timeout=60).stdout
    vals = {}
    for m in re.finditer(r"(v\([a-z0-9]+\)|@b1\[i\])\s*=\s*([-\d.eE+]+)", out):
        vals[m.group(1)] = float(m.group(2))
    return vals


# [1] sqrt(v): x^2+x-0.6=0 -> x=0.421954, v0=x^2=0.178045, i=x=0.421954
v = op("* sqrt bsrc op\nV1 in 0 DC 0.6\nR1 in n 1\nB1 n 0 I=sqrt(v(n))\n"
       ".control\nop\nprint v(n) @b1[i]\n.endc\n.end\n")
vn, ib = v.get("v(n)", -1), v.get("@b1[i]", 0.0)
ir1 = (0.6 - vn) / 1.0
check("[1] I=sqrt(v): DC op is the TRUE solution (v0=0.178045), KCL satisfied",
      abs(vn - 0.178045) < 1e-3 and abs(ib - ir1) < 1e-3,
      f"(v(n)={vn:.6f} vs 0.178045; imbalance |i_B1-i_R1|={abs(ib - ir1):.1e} "
      f"-- spurious would be v~0 with imbalance ~0.42)")

# [2] 0.1/v: v^2-v+0.1=0 -> v0=0.887298 (upper branch)
v = op("* recip bsrc op\nV1 in 0 DC 1\nR1 in n 1\nB1 n 0 I=0.1/v(n)\n"
       ".control\nop\nprint v(n)\n.endc\n.end\n")
vn = v.get("v(n)", -1)
check("[2] I=0.1/v: DC op is the analytic solution (v0=0.887298)",
      abs(vn - 0.887298) < 1e-4, f"(v(n)={vn:.6f} vs 0.887298)")

# [3] result-neutral: finite-derivative B-sources unchanged (exact ops)
cases = [
    ("v(n)*v(n)",       0.6, 0.421954),   # v^2+v-0.6=0 -> 0.421954
    ("v(n)*v(n)*v(n)",  0.6, 0.485537),   # v^3+v-0.6=0
    ("exp(v(n))",       0.5, -0.266249),  # exp(v)+v-0.5=0 (v<0)
    ("tanh(v(n))",      0.5, 0.252620),   # tanh(v)+v-0.5=0
]
worst = 0.0
for expr, vb, truth in cases:
    v = op(f"* fd bsrc\nV1 in 0 DC {vb}\nR1 in n 1\nB1 n 0 I={expr}\n"
           ".control\nop\nprint v(n)\n.endc\n.end\n")
    vn = v.get("v(n)", -99)
    worst = max(worst, abs(vn - truth))
check("[3] result-neutral: finite-derivative B-sources (v^2/v^3/exp/tanh) unchanged",
      worst < 1e-4, f"(worst |v-analytic| = {worst:.2e})")

if os.path.exists(os.path.join(HERE, "_b.cir")):
    os.remove(os.path.join(HERE, "_b.cir"))
print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
