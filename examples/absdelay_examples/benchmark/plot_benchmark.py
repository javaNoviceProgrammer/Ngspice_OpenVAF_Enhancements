#!/usr/bin/env python3
"""Plot KLU-vs-SPARSE benchmark results (version2 ngspice, absdelay mesh)."""
import os, csv
import numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
rows = list(csv.DictReader(open(os.path.join(HERE, "results", "timings.csv"))))
analyses = ["dc", "ac", "tran"]
data = {a: {} for a in analyses}   # data[a][solver] = (nodes[], secs[])
for r in rows:
    a = r["analysis"]; s = r["solver"]
    data[a].setdefault(s, ([], []))
    data[a][s][0].append(int(r["nodes"])); data[a][s][1].append(float(r["seconds"]))

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2))
cmap = {"dc": "C0", "ac": "C1", "tran": "C2"}
names = {"dc": "DC sweep", "ac": "AC sweep", "tran": "transient"}

# left: runtime vs nodes (KLU solid, SPARSE dashed)
for a in analyses:
    nK, tK = data[a]["KLU"]; nS, tS = data[a]["SPARSE"]
    o = np.argsort(nK)
    ax1.plot(np.array(nK)[o], np.array(tK)[o], "-o", color=cmap[a], ms=4, label=f"{names[a]} (KLU)")
    ax1.plot(np.array(nS)[o], np.array(tS)[o], "--s", color=cmap[a], ms=4, mfc="none", label=f"{names[a]} (SPARSE)")
ax1.set_xlabel("circuit size (nodes)"); ax1.set_ylabel("wall-clock time (s)")
ax1.set_title("Runtime vs size — KLU (solid) vs SPARSE (dashed)")
ax1.set_yscale("log"); ax1.grid(alpha=0.3, which="both"); ax1.legend(fontsize=8, ncol=1)

# right: speedup vs nodes
for a in analyses:
    nK, tK = data[a]["KLU"]; nS, tS = data[a]["SPARSE"]
    o = np.argsort(nK); nodes = np.array(nK)[o]
    sp = np.array(tS)[o] / np.array(tK)[o]
    ax2.plot(nodes, sp, "-o", color=cmap[a], ms=5, label=names[a])
ax2.axhline(1.0, color="gray", lw=0.8, ls=":")
ax2.set_xlabel("circuit size (nodes)"); ax2.set_ylabel("KLU speedup  (SPARSE / KLU)")
ax2.set_title("KLU speedup over SPARSE 1.3")
ax2.grid(alpha=0.3); ax2.legend(fontsize=9)

fig.suptitle("absdelay mesh benchmark — KLU vs SPARSE solver (version2 ngspice)", fontsize=13)
fig.tight_layout(rect=[0, 0, 1, 0.96])
out = os.path.join(HERE, "results", "benchmark.png")
fig.savefig(out, dpi=120); print("saved", out)
