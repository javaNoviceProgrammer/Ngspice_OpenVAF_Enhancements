#!/usr/bin/env python3
"""
plot_ddx.py -- DC, AC and transient demonstration of the ddx() operator, using
version11's own openvaf-r + ngspice-46.

`ddx_demo` is a nonlinear resistor id = Gbase*V + Isat*tanh(V/Vo) in parallel
with a capacitor Cpar. It uses ddx() to compute its own exact small-signal
conductance g(V) = d(id)/dV = Gbase + (Isat/Vo)*(1-tanh(V/Vo)^2) and exports it
(in mS) as the node voltage V(g). Driven through a series resistor rs so V(p,n)
is a genuine unknown, we show:

  ddx_dc.png    the ddx conductance vs bias exactly matches the closed form
  ddx_tran.png  under a large-signal sine, the ddx conductance tracks the
                instantaneous operating point (again matching the closed form)
  ddx_ac.png    that same ddx conductance is what sets the small-signal AC
                response (nonlinear R || C divider) -- curves shift with bias

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

GBASE, ISAT, VO, CPAR, RS = 1e-3, 1e-3, 1.0, 1e-6, 1e3
MODEL = f".model mm ddx_demo(Gbase={GBASE} Isat={ISAT} Vo={VO} Cpar={CPAR})"


def g_analytic(v):                       # small-signal conductance [S]
    return GBASE + (ISAT / VO) * (1.0 - np.tanh(v / VO) ** 2)


def run(deck, outfiles):
    path = os.path.join(HERE, "_ddx.cir")
    with open(path, "w") as fh:
        fh.write(deck)
    for f in outfiles:
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            os.remove(p)
    subprocess.run([NGSPICE, "-b", path], cwd=HERE, capture_output=True, text=True)
    return [np.loadtxt(os.path.join(HERE, f)) for f in outfiles]


def main():
    subprocess.run([OPENVAF, "ddx_demo.va", "-o", "ddx_demo.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ----- DC: conductance vs bias -----------------------------------------
    deck = ("* ddx DC conductance sweep\n"
            "vin in 0 dc 0\nrs in pp 1k\nn1 pp 0 gg mm\n" + MODEL + "\n"
            ".control\npre_osdi ddx_demo.osdi\n"
            "dc vin -12 12 0.25\nwrdata dc.txt v(pp) v(gg)\n.endc\n.end\n")
    (dc,) = run(deck, ["dc.txt"])
    vpn, g_mS = dc[:, 1], dc[:, 3]
    fig, ax = plt.subplots(figsize=(6.5, 4.4))
    ax.plot(vpn, 1e3 * g_analytic(vpn), "-", lw=2.5, color="tab:orange",
            label="analytic  Gbase+(Isat/Vo)(1-tanh$^2$)")
    ax.plot(vpn[::4], g_mS[::4], "o", ms=4, mfc="none", mec="tab:blue",
            label="ddx(id, V(p,n))  [simulated]")
    ax.set(xlabel="V(p,n) [V]", ylabel="small-signal conductance [mS]",
           title="DC: ddx computes the exact conductance g(V) across bias")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "ddx_dc.png"), dpi=150)
    plt.close(fig)
    dc_err = np.max(np.abs(g_mS - 1e3 * g_analytic(vpn)))

    # ----- Transient: conductance tracks the moving operating point --------
    deck = ("* ddx transient (large-signal sine)\n"
            "vin in 0 dc 0 sin(0 12 50)\nrs in pp 1k\nn1 pp 0 gg mm\n" + MODEL + "\n"
            ".control\npre_osdi ddx_demo.osdi\n"
            "tran 50u 20m\nwrdata tran.txt v(pp) v(gg)\n.endc\n.end\n")
    (tr,) = run(deck, ["tran.txt"])
    t, vpn_t, g_t = tr[:, 0], tr[:, 1], tr[:, 3]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.5, 5.6), sharex=True)
    a1.plot(t * 1e3, vpn_t, color="tab:green")
    a1.set(ylabel="V(p,n) [V]", title="Transient: ddx conductance follows the operating point")
    a1.grid(True, alpha=0.3)
    a2.plot(t * 1e3, 1e3 * g_analytic(vpn_t), "-", lw=2.5, color="tab:orange",
            label="analytic g(V(p,n)(t))")
    a2.plot(t[::12] * 1e3, g_t[::12], "o", ms=3.5, mfc="none", mec="tab:blue",
            label="ddx(id, V(p,n))  [simulated]")
    a2.set(xlabel="time [ms]", ylabel="conductance [mS]")
    a2.grid(True, alpha=0.3)
    a2.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "ddx_tran.png"), dpi=150)
    plt.close(fig)
    tr_err = np.max(np.abs(g_t - 1e3 * g_analytic(vpn_t)))

    # ----- AC: the ddx conductance sets the small-signal response ----------
    fig, ax = plt.subplots(figsize=(6.5, 4.4))
    colors = ["tab:blue", "tab:green", "tab:red"]
    ac_ok = True
    for vb, col in zip([0.0, 1.5, 4.0], colors):
        deck = (f"* ddx AC at bias {vb}\n"
                f"vin in 0 dc {vb} ac 1\nrs in pp 1k\nn1 pp 0 gg mm\n" + MODEL + "\n"
                ".control\npre_osdi ddx_demo.osdi\n"
                f"dc vin {vb} {vb} 1\nwrdata acop.txt v(pp) v(gg)\n"
                "ac dec 50 10 1e6\nwrdata acmag.txt vdb(pp)\n.endc\n.end\n")
        acop, acmag = run(deck, ["acop.txt", "acmag.txt"])
        vpp_dc = float(np.atleast_2d(acop)[0, 1])
        g_dc = g_analytic(vpp_dc)                      # S (matches ddx export)
        freq, mag_db = acmag[:, 0], acmag[:, 1]
        # analytic divider: H = 1/(1 + rs*g + j*w*rs*Cpar)
        w = 2 * np.pi * freq
        H = 1.0 / (1.0 + RS * g_dc + 1j * w * RS * CPAR)
        ax.semilogx(freq, mag_db, color=col, lw=1,
                    label=f"sim: Vbias={vb} V  (g={1e3*g_dc:.2f} mS)")
        ax.semilogx(freq, 20 * np.log10(np.abs(H)), "--", color=col, lw=2, alpha=0.7)
        if np.max(np.abs(mag_db - 20 * np.log10(np.abs(H)))) > 0.5:
            ac_ok = False
    ax.plot([], [], "k--", label="analytic (using ddx conductance)")
    ax.set(xlabel="frequency [Hz]", ylabel="|V(p,n)/V(in)| [dB]",
           title="AC: the ddx conductance sets the small-signal response (R $\\parallel$ C)")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "ddx_ac.png"), dpi=150)
    plt.close(fig)

    print("Wrote ddx_dc.png, ddx_tran.png, ddx_ac.png")
    print(f"  DC   max |g_ddx - g_analytic| = {dc_err:.2e} mS")
    print(f"  TRAN max |g_ddx - g_analytic| = {tr_err:.2e} mS")
    print(f"  AC   sim vs analytic (from ddx g): {'match' if ac_ok else 'MISMATCH'}")


if __name__ == "__main__":
    main()
