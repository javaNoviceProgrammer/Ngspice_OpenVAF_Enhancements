#!/usr/bin/env python3
"""Enhancement-177 figure: the pnoise folding referee and the folded-flicker fix.

Panel A -- flicker + conversion onoise spectrum: pnoise (fixed, live) lands on
the independent Python referee; the pre-fix behavior (recorded: it matched the
wrong-frequency model digit-for-digit) overestimates by ~21% at 1 kHz and
worsens as f decreases.

Panel B -- the folding ratio (pumped / unpumped noise floor, white thermal):
pnoise vs referee vs the TRNOISE transient Monte-Carlo arbiter (recorded from
the 198-segment Welch run; no shared code or theory with pnoise).

Run:  python3 make_pnoisefold_fig.py   ->  pnoisefold.png
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

G0, G1, R1, C1, F0 = 1e-3, 0.8e-3, 10e3, 100e-12, 1e6
KB, T = 1.380649e-23, 300.15
KF, AF, EF = 1e-9, 2.0, 1.0
M = 5


def zrow(f, g1):
    n = 2*M+1
    Y = np.zeros((n, n), complex)
    for ni in range(n):
        wn = 2*np.pi*(f + (ni-M)*F0)
        Y[ni, ni] += 1.0/R1 + 1j*wn*C1 + G0
        if ni+1 < n:
            Y[ni, ni+1] += +1j*g1/2
        if ni-1 >= 0:
            Y[ni, ni-1] += -1j*g1/2
    return np.linalg.inv(Y)[M, :]


def referee(f, g1, I=None, wrong=False):
    Z = zrow(f, g1)
    tot = 0.0
    for mi in range(2*M+1):
        k = mi - M
        fsrc = f if wrong else abs(f + k*F0)
        S = 4*KB*T/R1 + (KF*I**AF/fsrc**EF if I is not None else 0.0)
        tot += abs(Z[mi])**2 * S
    return tot


def run(name, deck):
    p = os.path.join(HERE, name)
    open(p, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, cwd=HERE)
    return r.stdout + r.stderr


DECK = """* flicker folding
V1 lo 0 SIN(0 1 1meg)
VDC a 0 DC 1
R1 a b rmod 10k
B1 b 0 I=(1m + 0.8m*v(lo))*v(b)
C1 b 0 100p
.model rmod R(kf=1e-9 af=2 ef=1)
.pnoise 1meg 1u b 1024 6 50 5u b vdc dec 4 500 200k
.control
run
print onoise_spectrum
setplot pss1
wrdata pnfig_td.csv v(b)
.endc
.end
"""
out = run("_fig.cir", DECK)
pts = {}
for m in re.finditer(r"^\d+\s+([\d.eE+-]+)\s+([\d.eE+-]+)", out, re.M):
    pts[float(m.group(1))] = float(m.group(2))
rows = [l.split() for l in open(os.path.join(HERE, "pnfig_td.csv")) if l.strip()]
I0 = (1.0 - float(rows[0][1])) / R1

fs = sorted(pts)
fgrid = np.logspace(math.log10(fs[0]), math.log10(fs[-1]), 60)
ref_c = [referee(f, G1, I0) for f in fgrid]
ref_w = [referee(f, G1, I0, wrong=True) for f in fgrid]

fig, (axA, axB) = plt.subplots(1, 2, figsize=(11.5, 4.8))
axA.loglog(fgrid, ref_w, "--", color="#d62728", lw=1.8,
           label="wrong-frequency model (= pre-fix pnoise, digit-for-digit)")
axA.loglog(fgrid, ref_c, "-", color="#1f77b4", lw=1.8,
           label="independent referee (source freq per sideband)")
axA.loglog(fs, [pts[f] for f in fs], "o", ms=7, mfc="none", mew=1.8,
           color="#2ca02c", label="pnoise (fixed, simulated)")
axA.set_xlabel("frequency [Hz]")
axA.set_ylabel(r"onoise  [V$^2$/Hz]")
axA.set_title("A. folded flicker through LPTV conversion")
axA.legend(fontsize=8.5)
axA.grid(alpha=0.3, which="both")

# Panel B: folding ratio, white
fsB = [50e3, 100e3, 150e3]
ratio_ref = [referee(f, G1)/referee(f, 0.0) for f in fsB]
out_p = run("_p.cir", DECK.replace("R1 a b rmod 10k", "R1 a b 10k")
            .replace(".model rmod R(kf=1e-9 af=2 ef=1)\n", "")
            .replace("dec 4 500 200k", "lin 3 50k 150k"))
out_n = run("_n.cir", DECK.replace("R1 a b rmod 10k", "R1 a b 10k")
            .replace(".model rmod R(kf=1e-9 af=2 ef=1)\n", "")
            .replace("0.8m*v(lo)", "0*v(lo)")
            .replace("dec 4 500 200k", "lin 3 50k 150k"))


def tab(o):
    d = {}
    for m in re.finditer(r"^\d+\s+([\d.eE+-]+)\s+([\d.eE+-]+)", o, re.M):
        d[float(m.group(1))] = float(m.group(2))
    return d


tp, tn = tab(out_p), tab(out_n)
ratio_pn = [tp[f]/tn[f] for f in fsB]
mc = [1.920, 1.855, 1.851]     # recorded 198-segment Welch TRNOISE Monte Carlo
x = np.arange(3)
w = 0.25
axB.bar(x-w, ratio_ref, w, label="referee", color="#1f77b4")
axB.bar(x,   ratio_pn,  w, label="pnoise (simulated)", color="#2ca02c")
axB.bar(x+w, mc, w, label="TRNOISE Monte-Carlo (recorded, ±3%)", color="#9467bd")
axB.set_xticks(x)
axB.set_xticklabels(["50 kHz", "100 kHz", "150 kHz"])
axB.set_ylabel("pumped / unpumped noise floor")
axB.set_ylim(0, 2.4)
axB.set_title("B. white-noise folding ratio: three-way agreement")
axB.legend(fontsize=8.5)
axB.grid(axis="y", alpha=0.3)

fig.suptitle("pnoise noise-folding referee: folded sidebands evaluated at their "
             "SOURCE frequency (Enhancement-177)", fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.93])
o = os.path.join(HERE, "pnoisefold.png")
fig.savefig(o, dpi=110)
print("wrote", o)
