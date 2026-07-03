#!/usr/bin/env python3
"""
plot_table.py -- DC, AC and transient plots of the Enhancement-16 `$table_model`
lookup-table interpolation, using version11's own openvaf-r + ngspice.

Produces three PNGs:
  table_dc.png    the interpolated transfer function and the file-based I-V curve,
                  with the tabulated grid points marked (shows linear interp +
                  constant/linear extrapolation)
  table_ac.png    the small-signal conductance g = dI/dV vs bias -- the simulated
                  AC conductance lands exactly on the analytic piecewise-constant
                  table slope (the Jacobian the interpolation supplies)
  table_tran.png  a large-signal sine through the transfer table: V(out)(t) tracks
                  table(V(in)(t)) instantaneously

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE

XFER_XP, XFER_FP = [0.0, 1.0, 2.0, 3.0], [0.0, 1.0, 4.0, 9.0]
IV_XP = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2]
IV_FP = [0.0, 1e-5, 5e-5, 2e-4, 6e-4, 1.5e-3, 3e-3]


def compile_va(name):
    subprocess.run([OPENVAF, f"{name}.va", "-o", f"{name}.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(deck, outfile):
    with open(os.path.join(HERE, "_p.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_p.cir"], cwd=HERE, capture_output=True, text=True)
    return np.atleast_2d(np.loadtxt(os.path.join(HERE, outfile)))


def iv_lin(v):
    v = np.asarray(v, float)
    out = np.interp(v, IV_XP, IV_FP)
    sl_hi = (IV_FP[-1] - IV_FP[-2]) / (IV_XP[-1] - IV_XP[-2])
    out = np.where(v > IV_XP[-1], IV_FP[-1] + (v - IV_XP[-1]) * sl_hi, out)
    return out


def main():
    compile_va("table_xfer")
    compile_va("table_res")

    # ---- DC: transfer function + file I-V curve ---------------------------
    d = run("* xfer dc\nvin in 0 dc 0\nn1 in out mm\n.model mm table_xfer()\n"
            ".control\npre_osdi table_xfer.osdi\ndc vin -1 5 0.05\n"
            "wrdata xfer.txt v(in) v(out)\n.endc\n.end\n", "xfer.txt")
    vin, vout = d[:, 1], d[:, 3]
    d = run("* res iv\nvb p 0 dc 0\nn1 p 0 mm\n.model mm table_res()\n"
            ".control\npre_osdi table_res.osdi\ndc vb -0.2 1.6 0.02\n"
            "wrdata iv.txt v(p) i(vb)\n.endc\n.end\n", "iv.txt")
    vp, ip = d[:, 1], -d[:, 3]  # current into the device

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.2))
    a1.plot(vin, vout, "-", lw=2, color="tab:blue", label="$table\\_model$ (simulated)")
    a1.plot(XFER_XP, XFER_FP, "o", ms=8, mfc="none", mec="tab:red", mew=2, label="table grid points")
    a1.axvspan(-1, 0, color="0.9"); a1.axvspan(3, 5, color="0.9")
    a1.set(xlabel="V(in) [V]", ylabel="V(out) [V]",
           title="DC: inline transfer table (grey = clamped extrapolation)")
    a1.grid(True, alpha=0.3); a1.legend()

    a2.plot(vp * 1e0, ip * 1e3, "-", lw=2, color="tab:green", label="$table\\_model$ I-V (simulated)")
    a2.plot(IV_XP, np.array(IV_FP) * 1e3, "o", ms=7, mfc="none", mec="tab:red", mew=2, label="table grid points")
    a2.axvspan(1.2, 1.6, color="0.9")
    a2.set(xlabel="V(p,n) [V]", ylabel="I [mA]",
           title="DC: file-based nonlinear resistor (grey = linear extrap)")
    a2.grid(True, alpha=0.3); a2.legend()
    fig.tight_layout(); fig.savefig(os.path.join(HERE, "table_dc.png"), dpi=150); plt.close(fig)

    # ---- AC: small-signal conductance vs bias -----------------------------
    biases = np.arange(0.1, 1.35, 0.1)
    g_sim = []
    for v0 in biases:
        a = run(f"* ac g {v0:.2f}\nvbias nn 0 dc {v0:.3f} ac 1\nn1 nn 0 mm\n.model mm table_res()\n"
                ".control\npre_osdi table_res.osdi\nac dec 1 1k 1k\n"
                "wrdata _ac.txt mag(i(vbias))\n.endc\n.end\n", "_ac.txt")
        g_sim.append(float(a[0, -1]))
    g_sim = np.array(g_sim)
    # analytic piecewise-constant slope
    vv = np.linspace(0, 1.2, 600)
    g_ref = np.gradient(np.interp(vv, IV_XP, IV_FP), vv)

    fig, ax = plt.subplots(figsize=(6.6, 4.3))
    ax.plot(vv, g_ref * 1e3, "-", lw=2, color="tab:orange", label="analytic table slope dI/dV")
    ax.plot(biases, g_sim * 1e3, "o", ms=6, color="tab:blue", label="AC small-signal g (simulated)")
    ax.set(xlabel="bias V(p,n) [V]", ylabel="conductance g [mS]",
           title="AC: small-signal conductance = table slope (the Jacobian)")
    ax.grid(True, alpha=0.3); ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(HERE, "table_ac.png"), dpi=150); plt.close(fig)

    # ---- Transient: V(out) tracks table(V(in)) ----------------------------
    d = run("* xfer tran\nvin in 0 dc 0 sin(1.5 1.5 100)\nn1 in out mm\n.model mm table_xfer()\n"
            ".control\npre_osdi table_xfer.osdi\ntran 20u 20m\n"
            "wrdata tr.txt v(in) v(out)\n.endc\n.end\n", "tr.txt")
    t, tvin, tvout = d[:, 0], d[:, 1], d[:, 3]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.8, 5.4), sharex=True)
    a1.plot(t * 1e3, tvin, color="tab:green")
    a1.set(ylabel="V(in) [V]", title="Transient: V(out) = table(V(in)) tracks instantaneously")
    a1.grid(True, alpha=0.3)
    a2.plot(t * 1e3, np.interp(tvin, XFER_XP, XFER_FP), "-", lw=3, color="tab:orange", alpha=0.6,
            label="table(V(in)) reference")
    a2.plot(t[::3] * 1e3, tvout[::3], "o", ms=3, mfc="none", mec="tab:blue", label="V(out) (simulated)")
    a2.set(xlabel="time [ms]", ylabel="V(out) [V]")
    a2.grid(True, alpha=0.3); a2.legend(loc="upper right")
    fig.tight_layout(); fig.savefig(os.path.join(HERE, "table_tran.png"), dpi=150); plt.close(fig)

    print("Wrote table_dc.png, table_ac.png, table_tran.png")


if __name__ == "__main__":
    main()
