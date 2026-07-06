#!/usr/bin/env python3
"""Render the Enhancement-74 benchmark plots from results.json."""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
PLOTS = os.path.join(HERE, "plots")
os.makedirs(PLOTS, exist_ok=True)

res = json.load(open(os.path.join(HERE, "results.json")))

# scaling: wall time vs ladder size
sc = res["scaling"]
n = [r["n"] for r in sc]
fig, ax = plt.subplots(figsize=(7, 4.5))
ax.loglog(n, [r["bi_s"] for r in sc], "o-", label="built-in R + C")
ax.loglog(n, [r["osdi_s"] for r in sc], "s-", label="OSDI rcseg (Verilog-A)")
ax.set_xlabel("ladder segments N")
ax.set_ylabel("transient wall time [s]")
ax.set_title("RC-ladder transient: wall time vs circuit size")
ax.grid(True, which="both", alpha=0.3)
ax.legend()
fig.tight_layout()
fig.savefig(os.path.join(PLOTS, "scaling.png"), dpi=110)
plt.close(fig)

# twin throughput bars
tw = res["twins"]
labels = [r["bench"] for r in tw]
x = range(len(tw))
fig, ax = plt.subplots(figsize=(7, 4.5))
w = 0.38
ax.bar([i - w / 2 for i in x], [r["builtin_s"] for r in tw], w, label="built-in")
ax.bar([i + w / 2 for i in x], [r["osdi_s"] for r in tw], w, label="OSDI (Verilog-A)")
for i, r in enumerate(tw):
    ax.text(i + w / 2, r["osdi_s"], f" ×{r['ratio']:.2f}", ha="center", va="bottom")
ax.set_xticks(list(x))
ax.set_xticklabels(labels)
ax.set_ylabel("transient wall time [s], median of 3")
ax.set_title("Twin circuits: identical physics, OSDI vs built-in")
ax.legend()
fig.tight_layout()
fig.savefig(os.path.join(PLOTS, "throughput.png"), dpi=110)
plt.close(fig)

# compile times
if res.get("compile"):
    co = sorted(res["compile"], key=lambda r: r["seconds"])
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.barh([r["model"] for r in co], [r["seconds"] for r in co])
    for i, r in enumerate(co):
        ax.text(r["seconds"], i, f" {r['seconds']:.2f} s ({r['loc']} LOC)",
                va="center", fontsize=8)
    ax.set_xlabel("openvaf-r compile time [s], median of 3")
    ax.set_title("Flagship compact-model compile times")
    ax.margins(x=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, "compile_times.png"), dpi=110)
    plt.close(fig)

print("plots written to plots/")
