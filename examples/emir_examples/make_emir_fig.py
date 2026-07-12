#!/usr/bin/env python3
"""Enhancement-158 figure: power-grid EMIR (IR-drop + electromigration).

A supply rail (1 V) feeds a 10-segment resistive ladder; every tap draws the
same current, so the segments near the pad carry the most current. The wire
widths are tapered toward the pad -- but two segments are deliberately
under-sized, creating electromigration hot-spots.

Panel A -- node voltage along the ladder: the IR-drop accumulates from the pad
to the far tap; the dashed line marks the 10%-of-rail budget.

Panel B -- per-segment current density J vs the EM limit Jmax. The trunk carries
the most current yet stays under the limit because it is wide; the two pinched
segments violate Jmax even at lower current -- electromigration is set by current
DENSITY, not current.

Run:  python3 make_emir_fig.py   ->  emir_grid.png
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

W = tempfile.mkdtemp(prefix="emir_fig_")
N = 10
I0 = 20e-3          # per-tap load current
RSEG = 0.2          # per-segment resistance
THICK = 5e-7
JMAX = 1.8e11        # between the tapered-design density (1.2e11) and the pinches

# tapered widths ~ carried current, with two deliberately pinched segments
widths = []
for k in range(1, N + 1):
    carried = (N - k + 1) * I0
    w = carried / 6e4              # nominal width for a ~constant-J design
    if k in (4, 7):               # under-sized hot-spots
        w *= 0.45
    widths.append(w)

lines = ["* emir grid figure", "Vdd vdd 0 dc 1.0"]
prev = "vdd"
for k in range(1, N + 1):
    node = f"n{k}"
    lines.append(f"Rw{k} {prev} {node} {RSEG} w={widths[k-1]:.4g}")
    lines.append(f"Il{k} {node} 0 dc {I0}")
    prev = node
deck = "\n".join(lines) + "\n"


def run(control):
    with open(os.path.join(W, "g.cir"), "w") as f:
        f.write(deck + ".control\n" + control + "\n.endc\n.end\n")
    return subprocess.run([NGSPICE, "-b", "g.cir"], cwd=W,
                          capture_output=True, text=True).stdout


# node voltages (IR drop)
run(f"op\nwrdata v.dat " + " ".join(f"v(n{k})" for k in range(1, N + 1)))
volts = []
for ln in open(os.path.join(W, "v.dat")):
    p = ln.split()
    # wrdata writes  x1 y1 x2 y2 ...  ; take every 2nd column (the values)
    if len(p) >= 2 * N:
        volts = [float(p[2 * i + 1]) for i in range(N)]
        break

# electromigration table (all segments)
log = run(f"emir thick {THICK:g} jmax {JMAX:g} top 100")
seg = {}
for m in re.finditer(r"^\s+(rw\d+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+(FAIL|ok)\s*$",
                     log, re.M):
    seg[m.group(1).lower()] = dict(i=float(m.group(2)), j=float(m.group(4)),
                                   status=m.group(6))
idx = list(range(1, N + 1))
Js = [seg[f"rw{k}"]["j"] for k in idx]
Is = [seg[f"rw{k}"]["i"] for k in idx]
fail = [seg[f"rw{k}"]["status"] == "FAIL" for k in idx]

fig, (axA, axB) = plt.subplots(1, 2, figsize=(11, 4.3))

# --- Panel A: IR-drop along the ladder ---
axA.plot([0] + idx, [1.0] + volts, "o-", color="#1f77b4", lw=2, ms=5)
axA.axhline(1.0, color="#2ca02c", lw=1, ls=":", label="ideal rail (1 V)")
axA.axhline(0.9, color="#d62728", lw=1, ls="--", label="10% IR-drop budget")
axA.set_xlabel("tap position (segments from pad)")
axA.set_ylabel("node voltage [V]")
axA.set_title(f"A. IR-drop: rail sags to {volts[-1]:.3f} V at the far tap")
axA.legend()
axA.grid(True, alpha=0.3)

# --- Panel B: current density vs EM limit ---
colors = ["#d62728" if f else "#1f77b4" for f in fail]
axB.bar(idx, [j / 1e10 for j in Js], color=colors, width=0.7)
axB.axhline(JMAX / 1e10, color="#d62728", lw=1.5, ls="--", label="Jmax (EM limit)")
axtwin = axB.twinx()
axtwin.plot(idx, [i * 1e3 for i in Is], "k.-", lw=1.2, ms=6, alpha=0.7,
            label="segment current")
axtwin.set_ylabel("segment current [mA]")
axB.set_xlabel("segment (from pad)")
axB.set_ylabel(r"current density  J  [$10^{10}$ A/m$^2$]")
axB.set_title("B. Electromigration: density, not current, sets risk")
h1, l1 = axB.get_legend_handles_labels()
h2, l2 = axtwin.get_legend_handles_labels()
axB.legend(h1 + h2, l1 + l2, loc="upper right", fontsize=9)
axB.grid(True, axis="y", alpha=0.3)

fig.tight_layout()
out = os.path.join(HERE, "emir_grid.png")
fig.savefig(out, dpi=110)
print("wrote", out)
