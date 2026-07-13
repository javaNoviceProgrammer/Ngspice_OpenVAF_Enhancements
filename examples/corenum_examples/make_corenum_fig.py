#!/usr/bin/env python3
"""Enhancement-181 figure: the core-numerics audit.

Panel A -- the integrator certified: max relative residual of the exact BDF-k
formula over the accepted trajectory's uniform stencils, per order (live) --
machine precision at every order 1-6.

Panel B -- measured global convergence on the RC decay under `.options
ordfix` (live): error vs step size for trap and Gear 1-3, with the nominal
h^k reference slopes.

Run:  python3 make_corenum_fig.py   ->  corenum.png
"""
import math
import os
import re
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

TAU = 1e-3


def run(name, deck):
    p = os.path.join(HERE, name)
    open(p, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, cwd=HERE)
    return r.stdout + r.stderr


def traj(k, h):
    out = run(f"_fj{k}.cir", f"""* traj gear{k}
R1 a 0 1k
C1 a 0 1u ic=1
.options method=gear maxord={k} ordfix={k} reltol=1e-3 abstol=1e-12
.tran {h} 10m 0 {h} uic
.control
set numdgt=15
run
print v(a)
.endc
.end
""")
    return [(float(m.group(1)), float(m.group(2)))
            for m in re.finditer(r"^\d+\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s*$", out, re.M)]


def bdf_residual(pts, k, h):
    worst = 0.0
    for n in range(k + 1, len(pts)):
        ts = [pts[n - j][0] for j in range(k + 1)]
        if any(not (0.98 * h < (ts[j] - ts[j + 1]) < 1.02 * h) for j in range(k)):
            continue
        ys = [pts[n - j][1] for j in range(k + 1)]
        tn = ts[0]
        ydot = 0.0
        for j in range(k + 1):
            others = [ts[m] for m in range(k + 1) if m != j]
            num = 0.0
            for m in range(len(others)):
                prod = 1.0
                for q in range(len(others)):
                    if q != m:
                        prod *= (tn - others[q])
                num += prod
            den = 1.0
            for o in others:
                den *= (ts[j] - o)
            ydot += (num / den) * ys[j]
        worst = max(worst, abs(ydot + ys[0] / TAU) / (abs(ys[0]) / TAU + 1e-30))
    return worst


def endpoint(opt, h):
    out = run("_fe.cir", f"""* slope
R1 a 0 1k
C1 a 0 1u ic=1
.options {opt} reltol=1e-3 abstol=1e-12
.tran {h} 1m 0 {h} uic
.control
set numdgt=15
run
let ve = v(a)[length(v(a))-1]
print ve
.endc
.end
""")
    m = re.search(r"^ve = ([-\d.eE+]+)", out, re.M)
    return float(m.group(1)) if m else None


fig, (axA, axB) = plt.subplots(1, 2, figsize=(11.5, 4.8))

# Panel A
orders = [1, 2, 3, 4, 5, 6]
resids = [bdf_residual(traj(k, 100e-6), k, 100e-6) for k in orders]
axA.semilogy(orders, resids, "o-", ms=8, color="#2ca02c", lw=1.6,
             label="max BDF-k residual on the accepted trajectory (live)")
axA.axhline(1e-12, color="#d62728", ls="--", lw=1.4, label="certification bound 1e-12")
axA.set_ylim(1e-16, 1e-9)
axA.set_xlabel("Gear / BDF order k")
axA.set_ylabel("max relative formula residual")
axA.set_title("A. the integrator certified: ngspice's accepted points satisfy\n"
              "the exact BDF-k formula to machine precision, k = 1..6")
axA.legend(fontsize=8.5)
axA.grid(alpha=0.3, which="both")

# Panel B
REF = math.exp(-1.0)
hs = np.array([100e-6, 50e-6, 25e-6, 12.5e-6])
styles = [("trap", "method=trap ordfix=2", 2, "#1f77b4"),
          ("gear1", "method=gear maxord=1 ordfix=1", 1, "#9467bd"),
          ("gear2", "method=gear maxord=2 ordfix=2", 2, "#2ca02c"),
          ("gear3", "method=gear maxord=3 ordfix=3", 3, "#d62728")]
for label, opt, k, col in styles:
    errs = [abs(endpoint(opt, h) - REF) / REF for h in hs]
    axB.loglog(hs / TAU, errs, "o-", ms=6, color=col, lw=1.5, label=f"{label} (measured)")
    refline = errs[0] * (hs / hs[0]) ** k
    axB.loglog(hs / TAU, refline, ":", color=col, lw=1.1, alpha=0.7)
axB.set_xlabel("step size  h / tau")
axB.set_ylabel("relative endpoint error, RC decay")
axB.set_title("B. measured convergence under `.options ordfix`\n(dotted: nominal $h^k$ slopes)")
axB.legend(fontsize=8.5)
axB.grid(alpha=0.3, which="both")

fig.suptitle("Core-numerics audit: certify the 30-years-dormant Gear orders exactly "
             "(Enhancement-181)", fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.92])
o = os.path.join(HERE, "corenum.png")
fig.savefig(o, dpi=110)
print("wrote", o)
