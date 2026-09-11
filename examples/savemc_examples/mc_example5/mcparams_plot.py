#!/usr/bin/env python3
"""mc_example5: read the mcparams_*.csv .option savemc wrote and plot the draws.

Usage: python3 mcparams_plot.py [mcparams_<date>_<time>.csv]   (default: the newest here)

Makes draws_hist.png  -- the distribution of every drawn parameter
      pk_vs_r1.png    -- the peak of v(out) per sample (pk.txt, written by the deck)
                         against the drawn series resistance, coloured by the model's r
"""
import csv
import glob
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

here = os.path.dirname(os.path.abspath(__file__))
path = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(here, "mcparams_*.csv")))[-1]

with open(path) as f:
    rows = list(csv.reader(f))
head, body = rows[0], rows[1:]
cols = {name: np.array([float(r[i]) if r[i] != "" else np.nan for r in body])
        for i, name in enumerate(head) if i >= 3}          # trial, analysis, status first
status = [r[2] for r in body]
print(f"{os.path.basename(path)}: {len(body)} rows, {len(cols)} drawn parameters: {', '.join(cols)}")
print(f"  {status.count('ok')} ok, {status.count('failed')} failed")

# --- every drawn parameter, as a histogram
names = [n for n in cols if not np.all(np.isnan(cols[n]))]
fig, axes = plt.subplots(2, (len(names) + 1) // 2, figsize=(3.6 * ((len(names) + 1) // 2), 6))
for ax, n in zip(axes.flat, names):
    v = cols[n][~np.isnan(cols[n])]
    ax.hist(v, bins=30, color="#4a7ebb", edgecolor="white")
    ax.set_title(f"{n}   mean {v.mean():.4g}, sd {v.std():.3g}", fontsize=9)
for ax in list(axes.flat)[len(names):]:
    ax.axis("off")
fig.suptitle(f"the draws of every sample -- {os.path.basename(path)}", fontsize=10)
fig.tight_layout()
fig.savefig(os.path.join(here, "draws_hist.png"), dpi=110)
print("  draws_hist.png")

# --- the peak per sample against the drawn R1 (pk.txt: wrdata of montecarlo1.pk; row k = sample k)
pkfile = os.path.join(here, "pk.txt")
if os.path.exists(pkfile) and "r1" in cols:
    pk = np.loadtxt(pkfile)[:, 1]
    n = min(len(pk), len(cols["r1"]))
    fig, ax = plt.subplots(figsize=(6, 4.2))
    c = cols["@rm[r]"][:n] if "@rm[r]" in cols else None
    sc = ax.scatter(cols["r1"][:n], pk[:n], c=c, cmap="viridis", s=14)
    if c is not None:
        fig.colorbar(sc, ax=ax, label="@rm[r]  (the model's drawn r, ohm)")
    ax.set_xlabel("r1  (the drawn series resistance, ohm)")
    ax.set_ylabel("peak of v(out)  (V)")
    ax.set_title("the step response's peak against the draw behind it", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(here, "pk_vs_r1.png"), dpi=110)
    print("  pk_vs_r1.png")
