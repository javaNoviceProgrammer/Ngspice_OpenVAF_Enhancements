#!/usr/bin/env python3
"""Render the KLU-vs-SPARSE solver stress plots from results.json."""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
PLOTS = os.path.join(HERE, "plots")
os.makedirs(PLOTS, exist_ok=True)
res = json.load(open(os.path.join(HERE, "results.json")))
SW = res["sweep"]

TOPOS = [("ladder1d", "1-D ladder"), ("mesh2d", "2-D mesh"), ("mesh3d", "3-D mesh")]
SP, KL = "#c1440e", "#1f6feb"          # sparse (rust), klu (blue)


def xy(rows, solver, field):
    """(nodes, acct[field]) pairs for a solver, skipping missing points."""
    xs, ys = [], []
    for r in rows:
        if solver in r and r[solver]["acct"].get(field) is not None:
            xs.append(r["nodes"])
            ys.append(r[solver]["acct"][field])
    return xs, ys


# ---- 1. total analysis time vs N (solid) + reorder (dashed), per topology ----
fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.4))
for ax, (key, title) in zip(axes, TOPOS):
    rows = SW[key]
    for solver, col, lab in ((("sparse", SP, "SPARSE 1.3")), ("klu", KL, "KLU")):
        x, y = xy(rows, solver, "analysis")
        if x:
            ax.loglog(x, y, "o-", color=col, label=f"{lab} total")
        xr, yr = xy(rows, solver, "reorder")
        if xr:
            ax.loglog(xr, yr, "--", color=col, alpha=.55, lw=1.3,
                      label=f"{lab} reorder")
    ax.set_title(title)
    ax.set_xlabel("nodes N")
    ax.grid(True, which="both", alpha=.3)
axes[0].set_ylabel("time [s]")
axes[0].legend(fontsize=8, loc="upper left")
fig.suptitle("DC operating-point solve time vs circuit size "
             "(total analysis solid, matrix reorder dashed)", fontsize=12)
fig.tight_layout(rect=(0, 0, 1, .95))
fig.savefig(os.path.join(PLOTS, "analysis_scaling.png"), dpi=115)
plt.close(fig)

# ---- 2. KLU speedup (sparse/klu total analysis) vs N, all topologies ----
fig, ax = plt.subplots(figsize=(7.2, 4.6))
marks = {"ladder1d": "o", "mesh2d": "s", "mesh3d": "^"}
for key, title in TOPOS:
    rows = SW[key]
    xs, sp = xy(rows, "sparse", "analysis")
    kd = dict(zip(*xy(rows, "klu", "analysis")))
    px = [n for n in xs if n in kd]
    py = [sp[xs.index(n)] / kd[n] for n in px]
    if px:
        ax.semilogx(px, py, marks[key] + "-", label=title)
ax.axhline(1.0, color="k", lw=.8, ls=":")
ax.set_xlabel("nodes N")
ax.set_ylabel("KLU speedup  (SPARSE analysis / KLU analysis)")
ax.set_title("KLU speedup over SPARSE 1.3 vs circuit size")
ax.grid(True, which="both", alpha=.3)
ax.legend()
fig.tight_layout()
fig.savefig(os.path.join(PLOTS, "speedup.png"), dpi=115)
plt.close(fig)

# ---- 3. cost breakdown (reorder/factor/solve) at the largest common size ----
fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.2))
parts = ["reorder", "factor", "solve"]
pcol = ["#6a3d9a", "#e08214", "#2a9d3a"]
for ax, (key, title) in zip(axes, TOPOS):
    rows = SW[key]
    common = [r for r in rows if "sparse" in r and "klu" in r]
    if not common:
        ax.set_visible(False)
        continue
    r = common[-1]
    for i, solver in enumerate(("sparse", "klu")):
        bottom = 0.0
        for p, c in zip(parts, pcol):
            v = r[solver]["acct"].get(p) or 0.0
            ax.bar(i, v, bottom=bottom, color=c,
                   label=p if i == 0 else None)
            bottom += v
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["SPARSE", "KLU"])
    ax.set_title(f"{title}  (N={r['nodes']})")
    ax.grid(True, axis="y", alpha=.3)
axes[0].set_ylabel("time [s]")
axes[0].legend(fontsize=9)
fig.suptitle("DC-op solver cost breakdown at the largest common size", fontsize=12)
fig.tight_layout(rect=(0, 0, 1, .95))
fig.savefig(os.path.join(PLOTS, "breakdown.png"), dpi=115)
plt.close(fig)

# ---- 4. peak memory vs N ----
fig, ax = plt.subplots(figsize=(7.2, 4.6))
for key, title in TOPOS:
    rows = SW[key]
    for solver, col in (("sparse", SP), ("klu", KL)):
        xs = [r["nodes"] for r in rows if solver in r and r[solver]["rss"]]
        ys = [r[solver]["rss"] / 1e6 for r in rows if solver in r and r[solver]["rss"]]
        if xs:
            ls = "-" if solver == "klu" else "--"
            ax.loglog(xs, ys, marks[key] + ls, color=col, alpha=.85,
                      label=f"{title} {solver.upper() if solver=='klu' else 'SPARSE'}")
ax.set_xlabel("nodes N")
ax.set_ylabel("peak RSS [MB]")
ax.set_title("Peak memory vs circuit size (solid KLU, dashed SPARSE)")
ax.grid(True, which="both", alpha=.3)
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(os.path.join(PLOTS, "memory.png"), dpi=115)
plt.close(fig)

# ---- 5. transient refactor regime ----
tr = res.get("transient")
if tr and "sparse" in tr and "klu" in tr:
    fig, ax = plt.subplots(figsize=(6.6, 4.4))
    labels = ["transient\nfactor", "transient\nsolve", "transient\nload"]
    keys = ["tfactor", "tsolve", None]
    sp = [tr["sparse"]["acct"].get("tfactor") or 0,
          tr["sparse"]["acct"].get("tsolve") or 0,
          tr["sparse"]["acct"].get("load") or 0]
    kl = [tr["klu"]["acct"].get("tfactor") or 0,
          tr["klu"]["acct"].get("tsolve") or 0,
          tr["klu"]["acct"].get("load") or 0]
    x = range(len(labels))
    ax.bar([i - .2 for i in x], sp, .4, color=SP, label="SPARSE 1.3")
    ax.bar([i + .2 for i in x], kl, .4, color=KL, label="KLU")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("time [s]")
    ax.set_title(f"Transient refactor regime: {tr['nodes']}-node 2-D mesh, "
                 f"{tr['sparse']['acct'].get('titer')} iterations")
    ax.grid(True, axis="y", alpha=.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, "transient.png"), dpi=115)
    plt.close(fig)

print("wrote plots:", ", ".join(sorted(os.listdir(PLOTS))))
