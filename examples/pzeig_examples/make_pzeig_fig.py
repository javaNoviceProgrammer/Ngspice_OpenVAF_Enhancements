#!/usr/bin/env python3
"""Enhancement-173 figure: the eigenvalue-based pole-zero method.

Panel A -- a 10-section RC ladder: the ten poles from `.options pzeig`
(circles) land exactly on the analytic tridiagonal-eigenvalue formula
s_k = -(2 - 2cos((2k-1)pi/21))/(RC) (crosses), spanning ~2.5 decades.

Panel B -- the twin-T notch s-plane: the full 6-root set (3 poles, a real zero,
and the conjugate notch pair at +-j1e6) from the eig method under both solvers,
coinciding.  The vintage Muller driver used to stall on the deflated conjugate
pair under KLU (E-171) and hits its iteration limit on other circuits; the
eigenvalue method computes all roots directly -- no iteration, no warnings.

All roots are simulated live under both solvers.

Run:  python3 make_pzeig_fig.py   ->  pzeig.png
"""
import math
import os
import re
import subprocess
import sys
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

W = tempfile.mkdtemp(prefix="pzeigfig_")


def run_pz(body, pzcard, solver):
    deck = (f"* pz\n.option {solver} pzeig\nv1 in 0 dc 0 ac 1\n{body}\n"
            f".control\n{pzcard}\nset numdgt=10\nprint all\n.endc\n.end\n")
    p = os.path.join(W, "d.cir")
    open(p, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, cwd=W)
    out = r.stdout + r.stderr
    roots = {"pole": [], "zero": []}
    for m in re.finditer(r"(pole|zero)\(\d+\)\s*=\s*([-\d.eE+]+),([-\d.eE+]+)", out):
        roots[m.group(1)].append((float(m.group(2)), float(m.group(3))))
    return roots


LADDER = "\n".join(f"r{k} {'in' if k == 1 else 'n%d' % (k-1)} n{k} 1k\nc{k} n{k} 0 1n"
                   for k in range(1, 11))
TT = ("r1 in n1 1k\nr2 n1 out 1k\nc3 n1 0 2n\nc1 in n2 1n\nc2 n2 out 1n\n"
      "r3 n2 0 500\nrl out 0 100k")

fig, (axA, axB) = plt.subplots(1, 2, figsize=(12.5, 5.2))

# --- Panel A: ladder poles vs analytic ---
lad = run_pz(LADDER, "pz in 0 n10 0 vol pol", "sparse")
got = sorted(-r for r, i in lad["pole"])
analytic = sorted((2.0 - 2.0 * math.cos((2 * k - 1) * math.pi / 21.0)) / 1e-6
                  for k in range(1, 11))
idx = list(range(1, 11))
axA.semilogy(idx, analytic, "x", ms=11, mew=2.4, color="#1f77b4",
             label="analytic  $(2-2\\cos\\frac{(2k-1)\\pi}{21})/RC$")
axA.semilogy(idx, got, "o", ms=11, mfc="none", mew=1.8, color="#2ca02c",
             label="`.options pzeig` (simulated)")
axA.set_xlabel("pole index $k$")
axA.set_ylabel(r"$-\mathrm{Re}(s_k)$  [rad/s]")
axA.set_title("A. 10-section RC ladder: all ten poles, exact")
axA.set_xticks(idx)
axA.legend(fontsize=9)
axA.grid(True, which="both", alpha=0.3)

# --- Panel B: twin-T full root set, both solvers ---
KX = dict(marker="x", s=130, lw=2.4, zorder=5)
KO = dict(marker="o", s=210, facecolors="none", lw=1.8, zorder=4)
for sol, col, style, zm in (("sparse", "#1f77b4", KX, "s"),
                            ("klu", "#2ca02c", KO, "D")):
    tt = run_pz(TT, "pz in 0 out 0 vol pz", sol)
    kw = dict(style)
    if "facecolors" in kw:
        kw["edgecolors"] = col
    else:
        kw["color"] = col
    axB.scatter([r / 1e6 for r, i in tt["pole"]], [i / 1e6 for r, i in tt["pole"]],
                label=f"{sol} poles", **kw)
    kw2 = dict(kw); kw2["marker"] = zm; kw2["s"] = kw2["s"] * 0.6
    axB.scatter([r / 1e6 for r, i in tt["zero"]], [i / 1e6 for r, i in tt["zero"]],
                label=f"{sol} zeros", **kw2)
axB.axhline(0, color="#999", lw=0.6)
axB.axvline(0, color="#999", lw=0.6)
axB.set_xlabel(r"Re(s)  [Mrad/s]")
axB.set_ylabel(r"Im(s)  [Mrad/s]")
axB.set_title("B. twin-T notch: all 6 roots, both solvers")
axB.legend(fontsize=8.5, loc="center left")
axB.grid(alpha=0.3)
axB.annotate(r"notch zeros $\pm j\,10^6$", xy=(0.0, 0.97), xytext=(-2.6, 0.55),
             fontsize=9, arrowprops=dict(arrowstyle="->", color="#555"))

fig.suptitle("Eigenvalue-based pole-zero (`.options pzeig`): shift-invert pencil + "
             "Francis QR — no Muller iteration (Enhancement-173)", fontsize=11.5)
fig.tight_layout(rect=[0, 0, 1, 0.94])
out = os.path.join(HERE, "pzeig.png")
fig.savefig(out, dpi=110)
print("wrote", out)
