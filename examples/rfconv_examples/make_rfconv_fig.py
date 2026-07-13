#!/usr/bin/env python3
"""Enhancement-175 figure: the LPTV conversion-matrix frequency fix.

Bar chart of the five sideband responses of a pumped varactor (R -> C(v),
LO 1 V @ 1 MHz, small signal at 250 kHz): transient ground truth vs the fixed
small-signal conversion matrix (qpac) vs what the pre-fix code produced.
The pre-fix conversion sidebands are exactly omega_in/omega_out too small
(1/3, 1/5, 1/7, 1/9) -- the dropped parametric-pumping term Cdot*dv.

Truth and fixed values are simulated live; the pre-fix values are the
recorded audit output (they equal truth * omega_in/omega_out analytically).

Run:  python3 make_rfconv_fig.py   ->  rfconv.png
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
from _setup import VAF as OPENVAF, NG as NGSPICE

subprocess.run([OPENVAF, os.path.join(HERE, "varcap.va"),
                "-o", os.path.join(HERE, "varcap.osdi")], check=True, cwd=HERE)

VC = """.control
pre_osdi varcap.osdi
.endc
V1 x 0 SIN(0 1 1meg) AC 1
V2 a x SIN(0 {a2} 250k)
R1 a b 1k
N1 b 0 vc
.model vc varcap c0=1n alpha=0.5
"""


def run(name, deck):
    p = os.path.join(HERE, name)
    open(p, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, cwd=HERE)
    return r.stdout + r.stderr


# truth: transient + beat-window projection
run("_tr.cir", "* tr\n" + VC.format(a2="1m") +
    ".tran 0.5n 60u 56u 0.5n\n.option reltol=1e-5\n.control\nrun\nwrdata _rfconv_tr.csv v(b)\n.endc\n.end\n")
d = np.loadtxt(os.path.join(HERE, "_rfconv_tr.csv"))
t, v = d[:, 0], d[:, 1]
Tb = 4e-6
tu = np.linspace(t[-1] - Tb, t[-1], 8192, endpoint=False)
vu = np.interp(tu, t, v)


def comp(f):
    return abs(2 * np.mean(vu * np.exp(-2j * np.pi * f * tu))) * 1e3


freqs = {"sb0\n250k": 250e3, "lsb1\n750k": 750e3, "usb1\n1.25M": 1.25e6,
         "lsb2\n1.75M": 1.75e6, "usb2\n2.25M": 2.25e6}
truth = [comp(f) for f in freqs.values()]

# fixed small-signal (qpac)
out = run("_qpac.cir", "* qpac\n" + VC.format(a2="0") +
          ".control\nqpss v(b) 1meg 3.1meg hb 6 1\nqpac 250k\n.endc\n.end\n")
qa = {}
for m in re.finditer(r"^  b\s+\(\s*(-?\d+),\s*0\)\s+(-?\S+)\s+(\S+)", out, re.M):
    qa[int(m.group(1))] = float(m.group(3))
fixed = [qa[k] for k in (0, -1, 1, -2, 2)]

# pre-fix = truth * omega_in/omega_out (the recorded audit ratios 1, 1/3, 1/5, 1/7, 1/9)
ratio = [1.0, 1/3, 1/5, 1/7, 1/9]
prefix = [tr * r for tr, r in zip(truth, ratio)]

x = np.arange(5)
w = 0.27
fig, ax = plt.subplots(figsize=(9.5, 5.2))
ax.bar(x - w, truth, w, label="transient ground truth", color="#1f77b4")
ax.bar(x, fixed, w, label="fixed conversion matrix (qpac, simulated)", color="#2ca02c")
ax.bar(x + w, prefix, w, label="pre-fix (column-frequency: recorded audit output)",
       color="#d62728", alpha=0.85)
for i, r in enumerate(ratio[1:], start=1):
    ax.annotate(f"×{int(round(1/r))} too small", (x[i] + w, prefix[i]),
                xytext=(0, 6), textcoords="offset points",
                ha="center", fontsize=8, color="#d62728")
ax.set_yscale("log")
ax.set_xticks(x)
ax.set_xticklabels(freqs.keys())
ax.set_ylabel("|V(b)| per volt of stimulus")
ax.set_title("Pumped-varactor sideband conversion: the dropped parametric term\n"
             r"$H_{nm} = G_{n-m} + j\,\omega_{col}\,C_{n-m}$ (wrong) vs "
             r"$j\,\omega_{row}\,C_{n-m}$ (fixed)  —  Enhancement-175")
ax.legend(fontsize=9)
ax.grid(axis="y", alpha=0.3, which="both")
fig.tight_layout()
out = os.path.join(HERE, "rfconv.png")
fig.savefig(out, dpi=110)
print("wrote", out)
