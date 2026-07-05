#!/usr/bin/env python3
"""
plot_discontinuity.py -- renders a PNG plot for the Enhancement-24 `$discontinuity`
example. A voltage step drives an RC through the model's switching threshold; the
model announces `$discontinuity(0)` once it is in the switched region. We run the
SAME transient with the announcement off (announce=0) and on (announce=1) and plot:

  (top)    V(out) (identical either way -- the announcement never changes the
           solution) with a marker at every accepted timepoint, plus V(a,b) and
           the switching threshold vth, shading the region where the discontinuity
           is announced. Far more timepoints land in that region when announced.
  (bottom) the transient timestep dt vs time: without the announcement the step
           grows to the tmax ceiling in the switched region; with it, the step is
           held fine there (which is what $discontinuity buys you).

Output: discontinuity_timesteps.png
"""
import os
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # repo root
from _setup import VAF as OPENVAF, NG as NGSPICE
VTH = 0.5


def run(announce):
    deck = (
        f"* disc plot announce={announce}\n"
        f"vin in 0 pulse(0 1 2u 10n 10n 1 2)\n"
        f"n1 in out dm\ncx out 0 4n\n"
        f".model dm disc_demo(announce={announce})\n"
        f".tran 1u 200u 0 25u\n"
        f".control\npre_osdi disc_demo.osdi\nrun\n"
        f"wrdata _pd{announce}.txt v(out)\n.endc\n.end\n"
    )
    with open(os.path.join(HERE, "_p.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_p.cir"], cwd=HERE, capture_output=True, text=True)
    d = np.loadtxt(os.path.join(HERE, f"_pd{announce}.txt"))
    # keep strictly increasing time (drop any duplicate/breakpoint artifacts)
    t, v = d[:, 0], d[:, 1]
    keep = np.concatenate(([True], np.diff(t) > 0))
    return t[keep], v[keep]


def main():
    subprocess.run([OPENVAF, "disc_demo.va", "-o", "disc_demo.osdi"],
                   cwd=HERE, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    t0, v0 = run(0)   # announcement off
    t1, v1 = run(1)   # announcement on
    us = 1e6

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.5, 6.6), sharex=True,
                                   gridspec_kw={"height_ratios": [1.0, 1.0]})

    # --- top: the solution + timepoints + announced region --------------------
    vab1 = 1.0 - v1
    # shade where the discontinuity is announced (V(a,b) < vth)
    ax1.fill_between(t1 * us, 0, 1, where=(vab1 < VTH), color="#ffe0a3", alpha=0.7,
                     transform=ax1.get_xaxis_transform(), label="$discontinuity announced")
    ax1.plot(t1 * us, v1, "-", color="#1f77b4", lw=1.8, zorder=3, label="V(out)")
    ax1.plot(t1 * us, vab1, "-", color="#7f7f7f", lw=1.3, label="V(a,b) = Vin - V(out)")
    ax1.axhline(VTH, color="#d62728", ls="--", lw=1.1, label=f"vth = {VTH}")
    # markers at every accepted timepoint (density = simulator effort)
    ax1.plot(t0 * us, v0, "o", color="#2ca02c", ms=4.5, zorder=4,
             label=f"timepoints, announce=0  (n={len(t0)})")
    ax1.plot(t1 * us, v1, ".", color="#9467bd", ms=5, zorder=5,
             label=f"timepoints, announce=1  (n={len(t1)})")
    ax1.set_ylabel("voltage [V]")
    ax1.set_ylim(-0.05, 1.15)
    ax1.set_title("Enhancement-24: $discontinuity(n) refines the transient timestep\n"
                  "(the solution is identical; the announcement only changes timestep control)")
    ax1.legend(loc="upper right", fontsize=7.5, ncol=2)
    ax1.grid(True, alpha=0.3)

    # --- bottom: the timestep dt vs time --------------------------------------
    # drop the final step (it lands exactly on tstop -- a breakpoint, not a real dt)
    ax2.semilogy(t0[1:-1] * us, np.diff(t0)[:-1] * us, "-o", color="#2ca02c", ms=4, lw=1.2,
                 label="announce=0  (step grows across the discontinuity)")
    ax2.semilogy(t1[1:-1] * us, np.diff(t1)[:-1] * us, "-", color="#9467bd", lw=1.5,
                 label="announce=1  (step held fine in the announced region)")
    ax2.set_xlabel("time [us]")
    ax2.set_ylabel("timestep dt [us]")
    ax2.legend(loc="lower right", fontsize=8)
    ax2.grid(True, which="both", alpha=0.3)

    fig.tight_layout()
    out = os.path.join(HERE, "discontinuity_timesteps.png")
    fig.savefig(out, dpi=130)
    print("wrote", out, f"({len(t0)} vs {len(t1)} timepoints)")


if __name__ == "__main__":
    main()
