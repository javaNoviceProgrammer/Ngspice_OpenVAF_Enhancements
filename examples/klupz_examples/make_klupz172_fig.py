#!/usr/bin/env python3
"""Enhancement-172 figure: balanced (differential) pole-zero under KLU.

Panel A -- s-plane root map of a differential RC bridge (output taken across the
floating pair a-b): poles at -1/(R1C1) = -1e6 and -1/(R2C2) = -5e5 rad/s and a
single zero at the origin.  This analysis form ('pz in 0 a b vol') was
"not supported with 'option KLU'" before E-172; the fixed KLU (circles) now
coincides with Sparse (crosses) exactly.

Panel B -- a differential output with a complex pole pair (series RLC branch vs
RC branch): KLU reproduces the conjugate pair and the real pole exactly.

All roots are simulated live under both solvers.

Run:  python3 make_klupz172_fig.py   ->  klupz_balanced.png
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

W = tempfile.mkdtemp(prefix="klupz172_")


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


BRIDGE = "r1 in a 1k\nc1 a 0 1n\nr2 in b 2k\nc2 b 0 1n"
DIFFRLC = "rr in a 10\nll a c 1m\ncc c 0 1n\nrx in b 1k\ncx b 0 1n"

cases = [
    ("A. differential RC bridge:  pz in 0 a b vol pz", BRIDGE, "pz in 0 a b vol pz"),
    ("B. differential complex poles:  pz in 0 c b vol pol", DIFFRLC, "pz in 0 c b vol pol"),
]

fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.2))
KX = dict(marker="x", s=130, lw=2.4, zorder=5)
KO = dict(marker="o", s=210, facecolors="none", lw=1.8, zorder=4)

for ax, (title, body, card) in zip(axes, cases):
    sp = pz_roots(body, card, "sparse")
    kl = pz_roots(body, card, "klu")
    for roots, col, lbl, style, zmark in ((sp, "#1f77b4", "Sparse", KX, "s"),
                                          (kl, "#2ca02c", "KLU (fixed)", KO, "D")):
        kw = dict(style)
        if "facecolors" in kw:
            kw["edgecolors"] = col
        else:
            kw["color"] = col
        ax.scatter([r / 1e6 for r, i in roots["pole"]],
                   [i / 1e6 for r, i in roots["pole"]], label=f"{lbl} poles", **kw)
        if roots["zero"]:
            kw2 = dict(kw)
            kw2["marker"] = zmark
            kw2["s"] = kw2["s"] * 0.6
            ax.scatter([r / 1e6 for r, i in roots["zero"]],
                       [i / 1e6 for r, i in roots["zero"]], label=f"{lbl} zeros", **kw2)
    ax.axhline(0, color="#999", lw=0.6)
    ax.axvline(0, color="#999", lw=0.6)
    ax.set_xlabel(r"Re(s)  [Mrad/s]")
    ax.set_ylabel(r"Im(s)  [Mrad/s]")
    ax.set_title(title, fontsize=10.5)
    ax.legend(fontsize=8.5)
    ax.grid(alpha=0.3)

fig.suptitle("Balanced (differential-output) pole-zero under KLU — was "
             "\"not supported\", now exact parity (Enhancement-172)", fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.93])
out = os.path.join(HERE, "klupz_balanced.png")
fig.savefig(out, dpi=110)
print("wrote", out)
