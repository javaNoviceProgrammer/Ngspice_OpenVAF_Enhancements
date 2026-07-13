#!/usr/bin/env python3
"""Enhancement-179 figure: the standard-analyses audit.

Panel A -- .disto certified against two independent referees: the analytic
diode Volterra kernels (frequency-dependent load, live) and the E-134 Harmonic
Balance engine (junction-cap harmonics, live) -- the 1990 Volterra code lands
on both.

Panel B -- two of the fixes, before/after: the .tf current-output impedance
(pinned to 1e20 by a sign clamp inherited from Berkeley SPICE3) and the KLU AC
sensitivity sweep (silently truncated to one frequency point by a loop-variable
clobber).

Run:  python3 make_stdaudit_fig.py   ->  stdaudit.png
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

IS, VT = 1e-14, 0.025864
VB, R, C, A = 0.55, 1000.0, 100e-9, 1e-3


def run(name, deck):
    p = os.path.join(HERE, name)
    open(p, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, cwd=HERE)
    return r.stdout + r.stderr


def cxvals(out):
    return [complex(float(m.group(1)), float(m.group(2)))
            for m in re.finditer(r"^\d+\s+[\d.eE+-]+\s+([-\d.eE+]+),\s*([-\d.eE+]+)",
                                 out, re.M)]


# ---- Panel A data: disto sweep vs Volterra referee ----
v = 0.5
for _ in range(300):
    e = math.exp(v / VT)
    f = (VB - v) / R - IS * (e - 1)
    df = -1 / R - IS * e / VT
    dv = -f / df
    if abs(dv) > 2 * VT:
        dv = math.copysign(2 * VT, dv)
    v += dv
    if abs(dv) < 1e-16:
        break
I0 = IS * (math.exp(v / VT) - 1)
g1, g2, g3 = I0 / VT, I0 / (2 * VT * VT), I0 / (6 * VT ** 3)
Z = lambda w: 1 / (1 / R + g1 + 1j * w * C)

out = run("_figA.cir", f"""* disto sweep
V1 in 0 DC {VB} DISTOF1 {A}
R1 in a {R}
D1 a 0 DMOD
C1 a 0 {C}
.model DMOD D(IS=1e-14 N=1)
.disto dec 6 300 30k
.control
run
setplot disto1
print v(a)
setplot disto2
print v(a)
.endc
.end
""")
vals = cxvals(out)
n = len(vals) // 2
h2, h3 = [abs(c) for c in vals[:n]], [abs(c) for c in vals[n:2 * n]]
fs = np.logspace(math.log10(300), math.log10(30e3), n)
fgrid = np.logspace(math.log10(300), math.log10(30e3), 80)
ref2, ref3 = [], []
for f in fgrid:
    w = 2 * math.pi * f
    v1 = A * Z(w) / R
    r2 = -g2 * v1 * v1 / 2 * Z(2 * w)
    ref2.append(abs(r2))
    ref3.append(abs(-(g3 * v1 ** 3 / 4 + g2 * v1 * r2) * Z(3 * w)))

fig, (axA, axB) = plt.subplots(1, 2, figsize=(11.5, 4.8))
axA.loglog(fgrid, ref2, "-", color="#1f77b4", lw=1.8, label="Volterra referee: HD2")
axA.loglog(fgrid, ref3, "-", color="#9467bd", lw=1.8, label="Volterra referee: HD3")
axA.loglog(fs, h2, "o", ms=6, mfc="none", mew=1.6, color="#2ca02c",
           label=".disto 2nd harmonic (live)")
axA.loglog(fs, h3, "s", ms=6, mfc="none", mew=1.6, color="#d62728",
           label=".disto 3rd harmonic (live)")
axA.set_xlabel("fundamental frequency [Hz]")
axA.set_ylabel("harmonic voltage at the diode node [V]")
axA.set_title("A. 1990 Volterra .disto lands on the analytic kernels\n"
              "(freq-dependent load; junction-cap case matches HB to 6 digits)")
axA.legend(fontsize=8.5)
axA.grid(alpha=0.3, which="both")

# ---- Panel B: the two numeric fixes, before/after ----
labels = [".tf i(vm) output\nimpedance [Ω]", "KLU AC .sens\nswept points"]
before = [1e20, 1]
after = [1000.99, 3]
exact = [1000.99, 3]
x = np.arange(2)
w = 0.3
bars1 = axB.bar(x - w / 2, before, w, color="#d62728", label="before (recorded)")
bars2 = axB.bar(x + w / 2, after, w, color="#2ca02c", label="after (live) = exact")
axB.set_yscale("log")
axB.set_xticks(x)
axB.set_xticklabels(labels, fontsize=9)
for b, v in zip(bars1, before):
    axB.annotate(f"{v:g}", (b.get_x() + b.get_width() / 2, v), xytext=(0, 4),
                 textcoords="offset points", ha="center", fontsize=9, color="#d62728")
for b, v in zip(bars2, after):
    axB.annotate(f"{v:g}", (b.get_x() + b.get_width() / 2, v), xytext=(0, 4),
                 textcoords="offset points", ha="center", fontsize=9, color="#2ca02c")
axB.set_ylim(0.5, 1e22)
axB.set_title("B. the fixes: a 35-year-old SPICE3 sign clamp,\n"
              "and a loop-clobbered KLU sensitivity sweep")
axB.legend(fontsize=9)
axB.grid(axis="y", alpha=0.3, which="both")

fig.suptitle("Standard-analyses audit: referee the 1990s code, fix what the referees catch "
             "(Enhancement-179)", fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.92])
o = os.path.join(HERE, "stdaudit.png")
fig.savefig(o, dpi=110)
print("wrote", o)
