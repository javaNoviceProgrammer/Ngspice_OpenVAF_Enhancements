#!/usr/bin/env python3
"""mc_example6: the results a run produced against the draws behind it -- from one csv.

Usage: python3 mcparams_plot.py [mcparams_<date>_<time>.csv]   (default: the newest here)
Makes over_vs_r1.png (overshoot against the drawn R1, coloured by the number of ringing
peaks) and tr_hist.png (the rise time of the 20 hand-run trials).
"""
import csv, glob, os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

here = os.path.dirname(os.path.abspath(__file__))
path = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(here, "mcparams_*.csv")))[-1]
with open(path) as f:
    rows = list(csv.reader(f))
head, body = rows[0], rows[1:]


def col(name):
    i = head.index(name)
    return np.array([float(r[i]) if i < len(r) and r[i] != "" else np.nan for r in body])


print(f"{os.path.basename(path)}: {len(body)} rows, columns {head}")

r1, over, npk = col("r1"), col("over"), col("npk")
m = ~np.isnan(over)
fig, ax = plt.subplots(figsize=(6, 4.2))
sc = ax.scatter(r1[m], over[m], c=npk[m], cmap="viridis", s=14)
fig.colorbar(sc, ax=ax, label="npk  (ringing peaks, track1.hits)")
ax.set_xlabel("r1  (the drawn series resistance, ohm)")
ax.set_ylabel("over  (overshoot, V)")
ax.set_title("-writemc: the overshoot of each sample against the draw behind it", fontsize=10)
fig.tight_layout()
fig.savefig(os.path.join(here, "over_vs_r1.png"), dpi=110)
print("  over_vs_r1.png")

tr = col("tr")
m = ~np.isnan(tr)
fig, ax = plt.subplots(figsize=(5, 3.6))
ax.hist(tr[m] * 1e6, bins=10, color="#4a7ebb", edgecolor="white")
ax.set_xlabel("tr  (10-90 % rise time, us)")
ax.set_ylabel("trials")
ax.set_title(f"writemc in a repeat loop: the meas result of {m.sum()} trials", fontsize=10)
fig.tight_layout()
fig.savefig(os.path.join(here, "tr_hist.png"), dpi=110)
print("  tr_hist.png")
