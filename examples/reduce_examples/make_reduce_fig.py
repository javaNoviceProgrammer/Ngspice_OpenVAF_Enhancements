#!/usr/bin/env python3
"""Generate reduce_ac.png: full vs TICER-reduced AC response of the demo RC ladder
at two reduction factors, from real ngspice runs. Usage: python3 make_reduce_fig.py"""
import os, re, subprocess, sys, tempfile
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
W = tempfile.mkdtemp(prefix="reduce_fig_")


def ladder(N=24, R=15, C="50f"):
    L, prev = ["* RC ladder parasitics"], "in"
    for k in range(1, N):
        L += [f"R{k} {prev} n{k} {R}", f"C{k} n{k} 0 {C}"]; prev = f"n{k}"
    L += [f"R{N} {prev} out {R}", f"Cout out 0 {C}"]
    return "\n".join(L) + "\n"


LAD = ladder()


def run(deck):
    open(os.path.join(W, "d.cir"), "w").write(deck)
    return subprocess.run([NGSPICE, "-b", "d.cir"], capture_output=True, text=True, cwd=W).stdout


def acdat(fn):
    x, y = [], []
    for line in open(os.path.join(W, fn)):
        q = line.split()
        if len(q) > 1:
            try: x.append(float(q[0])); y.append(float(q[1]))
            except ValueError: pass
    return x, y


run(f"{LAD}V1 in 0 DC 0 AC 1\nRload out 0 1k\n.control\nac dec 30 1meg 12g\nwrdata full.dat vdb(out)\n.endc\n.end\n")
ff, fdb = acdat("full.dat")

curves = []
for fac in (5, 40):
    out = run(f"{LAD}V1 in 0 DC 0 AC 1\n.control\nop\nreduce 3g factor {fac} keep out file r.sp name rc\n.endc\n.end\n")
    m = re.search(r"(\d+)\s+nodes\s*->\s*(\d+)\s+nodes", out)
    fn_, rn_ = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    # instantiate with the terminals in the emitted .subckt order (they ARE node names)
    terms = next((l.split()[2:] for l in open(os.path.join(W, "r.sp"))
                  if l.lower().lstrip().startswith(".subckt")), ["in", "out"])
    run(f".include r.sp\nxr {' '.join(terms)} rc\nV1 in 0 DC 0 AC 1\nRload out 0 1k\n"
        ".control\nac dec 30 1meg 12g\nwrdata r.dat vdb(out)\n.endc\n.end\n")
    rt, rdb = acdat("r.dat")
    curves.append((fac, fn_, rn_, rt, rdb))

fig, ax = plt.subplots(figsize=(7.6, 4.2))
ax.semilogx(ff, fdb, color="#334155", lw=3, label=f"full network ({curves[0][1]} nodes)", zorder=1)
for (fac, fn_, rn_, rt, rdb), c in zip(curves, ("#d1495b", "#2b8a3e")):
    ax.semilogx(rt, rdb, "--", color=c, lw=1.8,
                label=f"reduced, factor {fac} ({rn_} nodes, {fn_/rn_:.0f}× fewer)")
ax.axvline(3e9, color="#94a3b8", ls=":", lw=1)
ax.annotate("band of interest\nDC..3 GHz", (3.3e9, -30), fontsize=8, color="#555")
ax.set_xlabel("frequency (Hz)"); ax.set_ylabel("|v(out)|  (dB)")
ax.set_title("RC reduction (reduce): reduced network matches the full one in-band")
ax.grid(alpha=.3, which="both"); ax.legend(loc="lower left", fontsize=9)
fig.tight_layout()
out = os.path.join(HERE, "reduce_ac.png")
fig.savefig(out, dpi=120); print("wrote", out)
