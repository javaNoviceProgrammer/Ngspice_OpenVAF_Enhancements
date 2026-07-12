#!/usr/bin/env python3
"""Enhancement-171 figure: KLU pole-zero fixed (complex determinant + pivot tol).

Panel A -- s-plane pole map of a series RLC (exact poles -5000 +- j*999987.5).
Sparse (crosses) and the FIXED KLU (circles) coincide exactly.  The red markers
are the four bogus real "poles" the broken KLU determinant reported for this
same circuit before the fix (recorded pre-fix output: -100, -10, -0.89, 0 --
Muller wandering on a garbage determinant never left |s| < 100).

Panel B -- the hardest case: an RLC bandstop whose zeros lie ON the imaginary
axis (+- j1e6) next to its complex pole pair.  Fixed KLU reproduces Sparse's
full root set exactly (markers coincide).

All Sparse / fixed-KLU roots are simulated live by running the two solvers;
only the pre-fix garbage points are transcribed from the audit log.

Run:  python3 make_klupz_fig.py   ->  klupz.png
"""
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

W = tempfile.mkdtemp(prefix="klupzfig_")


def pz_roots(body, pzcard, solver):
    deck = (f"* pz\n.option {solver}\nv1 in 0 dc 0 ac 1\n{body}\n"
            f".control\n{pzcard}\nset numdgt=10\nprint all\n.endc\n.end\n")
    p = os.path.join(W, "d.cir")
    open(p, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, cwd=W)
    out = r.stdout + r.stderr
    roots = {"pole": [], "zero": []}
    for m in re.finditer(r"(pole|zero)\(\d+\)\s*=\s*([-\d.eE+]+),([-\d.eE+]+)", out):
        roots[m.group(1)].append((float(m.group(2)), float(m.group(3))))
    return roots


RLC = "r1 in n1 10\nl1 n1 out 1m\nc1 out 0 1n"
BS = "r1 in out 1k\nl1 out n1 1m\nc1 n1 0 1n\nrload out 0 10k"

rlc_sp = pz_roots(RLC, "pz in 0 out 0 vol pol", "sparse")
rlc_kl = pz_roots(RLC, "pz in 0 out 0 vol pol", "klu")
bs_sp = pz_roots(BS, "pz in 0 out 0 vol pz", "sparse")
bs_kl = pz_roots(BS, "pz in 0 out 0 vol pz", "klu")

# The garbage KLU output recorded during the audit, before the fix (this exact
# RLC deck): four spurious real poles.
RLC_KLU_BEFORE = [(-100.0, 0.0), (-10.0, 0.0), (-0.890111, 0.0), (0.0, 0.0)]

fig, (axA, axB) = plt.subplots(1, 2, figsize=(12.5, 5.4))
KX = dict(marker="x", s=130, lw=2.4, zorder=5)
KO = dict(marker="o", s=210, facecolors="none", lw=1.8, zorder=4)

# --- Panel A: RLC ---
sp = rlc_sp["pole"]
kl = rlc_kl["pole"]
axA.scatter([r / 1e6 for r, i in sp], [i / 1e6 for r, i in sp],
            color="#1f77b4", label="Sparse poles", **KX)
axA.scatter([r / 1e6 for r, i in kl], [i / 1e6 for r, i in kl],
            edgecolors="#2ca02c", label="KLU poles (fixed)", **KO)
axA.scatter([r / 1e6 for r, i in RLC_KLU_BEFORE], [i for r, i in RLC_KLU_BEFORE],
            color="#d62728", marker="X", s=90, zorder=3,
            label="KLU before fix (recorded): 4 bogus real poles")
axA.axhline(0, color="#999", lw=0.6)
axA.axvline(0, color="#999", lw=0.6)
axA.set_xlabel(r"Re(s)  [Mrad/s]")
axA.set_ylabel(r"Im(s)  [Mrad/s]")
axA.set_title("A. series RLC poles: KLU now matches Sparse exactly")
axA.legend(fontsize=8.5, loc="center left")
axA.grid(alpha=0.3)
axA.annotate(r"$-5000 \pm j\,999987.5$ (analytic)", xy=(-0.005, 1.0),
             xytext=(-0.0042, 0.72), fontsize=9,
             arrowprops=dict(arrowstyle="->", color="#555"))

# --- Panel B: bandstop ---
for roots, col, lbl, style in ((bs_sp, "#1f77b4", "Sparse", KX),
                               (bs_kl, "#2ca02c", "KLU (fixed)", KO)):
    kw = dict(style)
    if "facecolors" in kw:
        kw["edgecolors"] = col
    else:
        kw["color"] = col
    axB.scatter([r / 1e6 for r, i in roots["pole"]],
                [i / 1e6 for r, i in roots["pole"]], label=f"{lbl} poles", **kw)
    kw2 = dict(kw)
    kw2["marker"] = "s" if kw2["marker"] == "x" else "D"
    kw2["s"] = kw2["s"] * 0.6
    axB.scatter([r / 1e6 for r, i in roots["zero"]],
                [i / 1e6 for r, i in roots["zero"]], label=f"{lbl} zeros", **kw2)
axB.axhline(0, color="#999", lw=0.6)
axB.axvline(0, color="#999", lw=0.6)
axB.set_xlabel(r"Re(s)  [Mrad/s]")
axB.set_ylabel(r"Im(s)  [Mrad/s]")
axB.set_title("B. RLC bandstop: imaginary-axis zeros, full parity")
axB.legend(fontsize=8.5, loc="center left")
axB.grid(alpha=0.3)
axB.annotate(r"zeros at $\pm j/\sqrt{LC} = \pm j\,10^6$", xy=(0.0, 0.97),
             xytext=(-0.38, 0.62), fontsize=9,
             arrowprops=dict(arrowstyle="->", color="#555"))

fig.suptitle("KLU pole-zero: complex determinant + pivot-tolerance fixes "
             "(Enhancement-171)", fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.94])
out = os.path.join(HERE, "klupz.png")
fig.savefig(out, dpi=110)
print("wrote", out)
