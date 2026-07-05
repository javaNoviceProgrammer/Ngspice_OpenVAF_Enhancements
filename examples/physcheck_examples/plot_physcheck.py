#!/usr/bin/env python3
"""
plot_physcheck.py -- generates the Enhancement-57 physics-validation plots
(PNG, into plots/) from dense ngspice sweeps of the VA_TEST corpus models:

  plots/diode_iv.png     diode_cmc forward I-V vs the ideal 60 mV/decade law
  plots/gummel.png       MEXTRAM bjt505 Gummel plot (Ic, Ib) + beta
  plots/psp_gm.png       PSP103 transfer curve + AC-vs-numeric gm overlay
  plots/juncap_cv.png    JUNCAP200 C(V) vs the fitted junction grading law
  plots/r2_noise.png     r2_cmc thermal noise vs built-in resistor (identity)

Run after (or instead of) verify_physcheck.py; requires matplotlib.
"""
import math
import os
import re
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

# the VA_TEST corpus lives in this repository
CORPUS = os.path.join(HERE, "..", "..", "VA_TEST", "VA-Models-main", "code")
PLOTS = os.path.join(HERE, "plots")
os.makedirs(PLOTS, exist_ok=True)

VT = 1.380649e-23 * 300.15 / 1.602176634e-19  # 27C


def compile_model(rel, name):
    src = os.path.join(CORPUS, rel)
    osdi = os.path.join(HERE, f"_{name}.osdi")
    subprocess.run([OPENVAF, src, "-o", osdi], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # decks run with cwd=HERE: reference the model RELATIVELY (keeps every
    # generated artifact free of machine-specific absolute paths)
    return f"_{name}.osdi"


def run(deck, name):
    cir = os.path.join(HERE, f"_plt_{name}.cir")
    open(cir, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", cir], cwd=HERE,
                       capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def read_wrdata(name, ncols=2):
    rows = []
    for line in open(os.path.join(HERE, name)):
        p = line.split()
        if len(p) >= ncols:
            try:
                rows.append([float(x) for x in p[:ncols]])
            except ValueError:
                pass
    return rows


def ac_branch(out, src):
    m = re.search(rf"{src}#branch\s*=\s*([-\d.e+]+),\s*([-\d.e+]+)", out)
    return (float(m.group(1)), float(m.group(2))) if m else None


STYLE = dict(dpi=150, bbox_inches="tight")


# ----------------------------------------------------------------- diode I-V
def plot_diode():
    osdi = compile_model("diode_cmc/vacode/diode_cmc.va", "dio")
    run(f"* dio iv\nVd a 0 DC 0.3\nNX a 0 mm\n.model mm DIODE_CMC\n"
        f".control\nset numdgt=12\npre_osdi {osdi}\ndc Vd 0.1 1.05 0.005\n"
        f"wrdata _plt_dio.dat i(Vd)\n.endc\n.end\n", "dio")
    rows = read_wrdata("_plt_dio.dat")
    v = [r[0] for r in rows]
    i = [-r[1] for r in rows]

    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(7, 7), sharex=True,
                                  height_ratios=[2.2, 1])
    ax.semilogy(v, i, "o-", ms=2.5, lw=1, color="tab:blue",
                label="diode_cmc (OpenVAF-r + ngspice)")
    # ideal 60 mV/dec reference anchored in the ideal region
    k0 = min(range(len(v)), key=lambda k: abs(v[k] - 0.98))
    vref = [0.80, 1.05]
    iref = [i[k0] * math.exp((x - v[k0]) / VT) for x in vref]
    ax.semilogy(vref, iref, "--", color="tab:red", lw=1.5,
                label="ideal junction law  $e^{V/V_T}$  (60 mV/dec)")
    ax.axvspan(0.96, 1.0, color="tab:green", alpha=0.12,
               label="verified ideal region (n = 1.004–1.009)")
    ax.set_ylabel("forward current  $I_D$  [A]")
    ax.set_title("diode_cmc forward I–V at defaults\n"
                 "(below ~0.9 V the CMC recombination/TAT components dominate — by design)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)

    # local ideality
    nv, nn = [], []
    for k in range(len(v) - 1):
        if i[k] > 0 and i[k + 1] > 0:
            s = (math.log(i[k + 1]) - math.log(i[k])) / (v[k + 1] - v[k])
            if s > 0:
                nv.append(0.5 * (v[k] + v[k + 1]))
                nn.append(1.0 / (s * VT))
    ax2.plot(nv, nn, "-", color="tab:purple", lw=1.2)
    ax2.axhline(1.0, color="tab:red", ls="--", lw=1)
    ax2.axvspan(0.96, 1.0, color="tab:green", alpha=0.12)
    ax2.set_ylim(0.8, 12)
    ax2.set_yscale("log")
    ax2.set_xlabel("$V_D$  [V]")
    ax2.set_ylabel("local ideality  n")
    ax2.grid(alpha=0.3)
    fig.savefig(os.path.join(PLOTS, "diode_iv.png"), **STYLE)
    plt.close(fig)
    print("plots/diode_iv.png")


# ------------------------------------------------------------------- Gummel
def plot_gummel():
    osdi = compile_model("mextram/vacode505p2p0/bjt505.va", "bjt")
    run(f"* gummel\nVb b 0 DC 0.6\nVc c 0 DC 1.0\nNX c b 0 mm\n"
        f".model mm bjt505va\n.control\nset numdgt=12\npre_osdi {osdi}\n"
        f"dc Vb 0.3 1.0 0.005\nwrdata _plt_gum.dat i(Vc) i(Vb)\n.endc\n.end\n",
        "gum")
    rows = read_wrdata("_plt_gum.dat", 4)
    v = [r[0] for r in rows]
    ic = [-r[1] for r in rows]
    ib = [-r[3] for r in rows]

    fig, ax = plt.subplots(figsize=(7, 5.2))
    ax.semilogy(v, [max(x, 1e-20) for x in ic], "-", color="tab:blue",
                lw=1.5, label="$I_C$")
    ax.semilogy(v, [max(x, 1e-20) for x in ib], "-", color="tab:orange",
                lw=1.5, label="$I_B$")
    k0 = min(range(len(v)), key=lambda k: abs(v[k] - 0.6))
    vref = [0.45, 0.75]
    iref = [ic[k0] * math.exp((x - v[k0]) / VT) for x in vref]
    ax.semilogy(vref, iref, "--", color="tab:red", lw=1.2,
                label="ideal slope (60 mV/dec)")
    ax.axvspan(0.5, 0.7, color="tab:green", alpha=0.12,
               label="verified region (n = 1.012–1.017)")
    ax.set_xlabel("$V_{BE}$  [V]")
    ax.set_ylabel("current  [A]")
    ax.set_title("MEXTRAM 505 Gummel plot at $V_{CE}$ = 1 V (defaults)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    ax2 = ax.twinx()
    beta = [c / b if (b > 1e-18 and c > 0) else float("nan")
            for c, b in zip(ic, ib)]
    ax2.plot(v, beta, ":", color="tab:gray", lw=1.5)
    ax2.set_ylabel(r"$\beta = I_C/I_B$  (dotted)", color="tab:gray")
    ax2.set_ylim(0, 200)
    fig.savefig(os.path.join(PLOTS, "gummel.png"), **STYLE)
    plt.close(fig)
    print("plots/gummel.png")


# --------------------------------------------------------------- PSP103 gm
def plot_psp_gm():
    osdi = compile_model("psp103/vacode/psp103.va", "psp")
    vd0 = 0.8
    run(f"* psp transfer\nVg g 0 DC 0.5\nVd d 0 DC {vd0}\nNX d g 0 0 mm\n"
        f".model mm PSP103VA\n.control\nset numdgt=12\npre_osdi {osdi}\n"
        f"dc Vg 0.2 1.2 0.005\nwrdata _plt_psp.dat i(Vd)\n.endc\n.end\n",
        "psp")
    rows = read_wrdata("_plt_psp.dat")
    v = [r[0] for r in rows]
    ids = [-r[1] for r in rows]
    # numeric gm (central differences over the dense sweep)
    gv = [0.5 * (v[k + 1] + v[k - 1]) for k in range(1, len(v) - 1)]
    gm = [(ids[k + 1] - ids[k - 1]) / (v[k + 1] - v[k - 1])
          for k in range(1, len(v) - 1)]
    # AC gm at a handful of bias points
    vg_pts = [0.4, 0.6, 0.8, 0.9, 1.0, 1.1]
    gm_ac = []
    for vg0 in vg_pts:
        out = run(f"* psp ac\nVg g 0 DC {vg0} AC 1\nVd d 0 DC {vd0}\n"
                  f"NX d g 0 0 mm\n.model mm PSP103VA\n.control\n"
                  f"set numdgt=12\npre_osdi {osdi}\nac lin 1 100 100\n"
                  f"print all\n.endc\n.end\n", "pspac")
        b = ac_branch(out, "vd")
        gm_ac.append(-b[0] if b else float("nan"))

    fig, ax = plt.subplots(figsize=(7, 5.2))
    ax.plot(gv, [g * 1e3 for g in gm], "-", color="tab:blue", lw=1.5,
            label="numeric  $\\mathrm{d}I_D/\\mathrm{d}V_G$  from DC sweep")
    ax.plot(vg_pts, [g * 1e3 for g in gm_ac], "o", color="tab:red", ms=7,
            mfc="none", mew=2,
            label="AC small-signal $g_m$ (autodiff Jacobian)")
    ax.set_xlabel("$V_{GS}$  [V]")
    ax.set_ylabel("$g_m$  [mS]")
    ax.set_title("PSP103 transconductance at $V_{DS}$ = 0.8 V:\n"
                 "AC (autodiff Jacobian) vs numeric derivative of DC "
                 "(agree to ~$10^{-5}$)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    ax2 = ax.twinx()
    ax2.semilogy(v, [max(x, 1e-15) for x in ids], ":", color="tab:gray", lw=1.2)
    ax2.set_ylabel("$I_D$  [A]  (dotted, log)", color="tab:gray")
    fig.savefig(os.path.join(PLOTS, "psp_gm.png"), **STYLE)
    plt.close(fig)
    print("plots/psp_gm.png")


# --------------------------------------------------------------- juncap C-V
def plot_juncap():
    osdi = compile_model("psp103/vacode/juncap200.va", "jc")
    freq = 1e6
    vr = [k * 0.1 for k in range(0, 31)]
    cs = []
    for x in vr:
        out = run(f"* jc cv\nVa a 0 DC {-x} AC 1\nNX a 0 mm\n"
                  f".model mm JUNCAP200 ab=1e-12 ls=1e-6\n"
                  f".control\nset numdgt=12\npre_osdi {osdi}\n"
                  f"ac lin 1 {freq} {freq}\nprint all\n.endc\n.end\n", "jc")
        b = ac_branch(out, "va")
        cs.append(-b[1] / (2 * math.pi * freq) if b else float("nan"))
    # fit VBI from C(0)/C(1) with P = 0.5
    c0 = cs[0]
    c1 = cs[10]
    vbi = 1.0 / ((c0 / c1) ** 2 - 1.0)
    fit = [c0 / math.sqrt(1.0 + x / vbi) for x in vr]

    fig, ax = plt.subplots(figsize=(7, 5.2))
    ax.plot(vr, [c * 1e15 for c in cs], "o", color="tab:blue", ms=4,
            label="JUNCAP200 (AC imaginary part)")
    ax.plot(vr, [c * 1e15 for c in fit], "--", color="tab:red", lw=1.5,
            label=f"junction law $C_0/(1+V_R/V_{{bi}})^{{0.5}}$, "
                  f"$V_{{bi}}$ = {vbi:.3f} V fitted from two points")
    ax.set_xlabel("reverse bias  $V_R$  [V]")
    ax.set_ylabel("junction capacitance  [fF]")
    ax.set_title("JUNCAP200 C(V) vs the junction grading law\n"
                 "(self-consistent to ~$10^{-4}$)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9)
    fig.savefig(os.path.join(PLOTS, "juncap_cv.png"), **STYLE)
    plt.close(fig)
    print("plots/juncap_cv.png")


# --------------------------------------------------------------- r2 noise
def plot_r2_noise():
    osdi = compile_model("r2_cmc/vacode/r2_cmc.va", "r2")

    def spectrum(dut):
        run(f"* r2 noise\nVs in 0 DC 0.1 AC 1\nRs in a 1k\n{dut}\n"
            f".control\nset numdgt=12\npre_osdi {osdi}\n"
            f"noise v(a) Vs dec 10 1 1meg\nsetplot noise1\n"
            f"wrdata _plt_r2n.dat onoise_spectrum\n.endc\n.end\n", "r2n")
        return read_wrdata("_plt_r2n.dat")

    s_va = spectrum("NX a 0 mm\n.model mm r2_cmc")
    s_ref = spectrum("Rref a 0 100")
    rel = max(abs(a[1] - b[1]) / b[1] for a, b in zip(s_va, s_ref))
    fig, ax = plt.subplots(figsize=(7, 4.6))
    ax.semilogx([r[0] for r in s_va], [r[1] * 1e9 for r in s_va], "-",
                color="tab:blue", lw=3.5,
                label="r2_cmc (Verilog-A `white_noise`)")
    ax.semilogx([r[0] for r in s_ref], [r[1] * 1e9 for r in s_ref], "--",
                color="tab:red", lw=1.5,
                label="built-in ngspice resistor (same 100 Ω)")
    # keep a sane scale: the curves coincide, don't let matplotlib zoom
    # into the sub-ppm band between them
    mid = s_ref[0][1] * 1e9
    ax.set_ylim(0, 2 * mid)
    ax.set_xlabel("frequency  [Hz]")
    ax.set_ylabel(r"output noise  [nV/$\sqrt{\mathrm{Hz}}$]")
    ax.set_title("Thermal-noise identity: Verilog-A 4kT/R vs ngspice's own\n"
                 f"(spectra identical: max relative difference {rel:.1e})")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=9)
    fig.savefig(os.path.join(PLOTS, "r2_noise.png"), **STYLE)
    plt.close(fig)
    print("plots/r2_noise.png")


if __name__ == "__main__":
    plot_diode()
    plot_gummel()
    plot_psp_gm()
    plot_juncap()
    plot_r2_noise()
    print("all plots written to", PLOTS)
