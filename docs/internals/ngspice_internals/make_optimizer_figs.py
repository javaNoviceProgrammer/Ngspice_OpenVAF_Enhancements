#!/usr/bin/env python3
"""Generate the figures for ngspice_optimizer.md from real ngspice runs.

Usage:  python3 docs/internals/ngspice_internals/make_optimizer_figs.py
Writes PNGs into ngspice_optimizer_figs/. Needs matplotlib + numpy and the
committed ngspice binary (which has the `optimize` command).
"""
import os
import re
import subprocess
import tempfile

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
FIGS = os.path.join(HERE, "ngspice_optimizer_figs")
os.makedirs(FIGS, exist_ok=True)

# committed binary (has `optimize`); fall back to a local build
NG = os.path.join(ROOT, "bin", "macos", "apple-silicon", "ngspice")
if not os.path.isfile(NG):
    NG = os.path.join(ROOT, "ngspice-46", "build", "src", "ngspice")

# openvaf-r, to compile the Verilog-A models for the OSDI example
VAF = os.path.join(ROOT, "OpenVAF-master-20260610", "target", "opt", "openvaf-r")
if not os.path.isfile(VAF):
    VAF = os.path.join(ROOT, "bin", "macos", "apple-silicon", "openvaf-r")
OPT_EX = os.path.join(ROOT, "examples", "optimize_examples")

BLUE, ORANGE, GREEN, RED, GREY = "#2563eb", "#ea7317", "#159947", "#cf222e", "#6b7280"
plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.alpha": 0.3,
                     "figure.dpi": 130, "savefig.bbox": "tight"})


def run(deck):
    with tempfile.NamedTemporaryFile("w", suffix=".cir", delete=False) as f:
        f.write(deck); p = f.name
    try:
        r = subprocess.run([NG, "-b", p], capture_output=True, text=True, timeout=120)
    finally:
        os.remove(p)
    return r.stdout + r.stderr


def wrdata(deck_body, outcols, fname):
    """Run an analysis writing `outcols` via wrdata; return the numeric columns."""
    tmp = os.path.join(tempfile.gettempdir(), fname)
    deck = (deck_body + f"\n.control\nrun\nwrdata {tmp} {outcols}\n.endc\n.end\n")
    run(deck)
    rows = []
    with open(tmp) as fh:
        for ln in fh:
            try:
                rows.append([float(x) for x in ln.split()])
            except ValueError:
                pass
    os.remove(tmp)
    return np.array(rows)


# ---------------------------------------------------------------- Fig 1: cost bowl
def fig_cost_bowl():
    R = np.linspace(100, 10000, 600)
    vout = 1000.0 / (R + 1000.0)          # divider: v(out) = R2/(R1+R2), R2=1k
    cost = (vout - 0.3) ** 2
    Rstar = 1000.0 * (1 / 0.3 - 1)        # 2333.3
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.plot(R, cost, color=BLUE, lw=2)
    ax.axvline(Rstar, color=GREEN, ls="--", lw=1.5)
    ax.plot([Rstar], [0], "o", color=GREEN, ms=8, zorder=5)
    ax.annotate(f"optimum\nR1 = {Rstar:.0f} Ω", (Rstar, 0.0),
                xytext=(Rstar + 1400, 0.010), color=GREEN,
                arrowprops=dict(arrowstyle="->", color=GREEN))
    ax.set_xlabel("R1  (Ω)"); ax.set_ylabel("cost  (v(out) − 0.3)²")
    ax.set_title("The optimizer looks for the bottom of this 'cost valley'")
    fig.savefig(os.path.join(FIGS, "cost_bowl.png")); plt.close(fig)


# --------------------------------------------------------------- Fig 2: convergence
def fig_convergence():
    deck = ("cost convergence\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n.control\n"
            "optimize -param R1 1k 100 10k -analysis op -minimize (v(out)-0.3)^2 "
            "-tol 1e-14 -verbose\n.endc\n.end\n")
    out = run(deck)
    it, cost = [], []
    for m in re.finditer(r"iter\s+(\d+)\s+best cost\s+([-\d.eE+]+)", out):
        it.append(int(m.group(1))); cost.append(float(m.group(2)))
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.semilogy(it, np.maximum(cost, 1e-24), "o-", color=ORANGE, ms=4, lw=1.5)
    ax.set_xlabel("iteration"); ax.set_ylabel("best cost so far  (log scale)")
    ax.set_title("Cost falls toward zero as the search homes in")
    fig.savefig(os.path.join(FIGS, "convergence.png")); plt.close(fig)


# --------------------------------------------------------------- Fig 3: AC response
def fig_ac_response():
    body = ("ac lowpass\nV1 in 0 ac 1\nR1 in out {R}\nC1 out 0 100n\n"
            ".ac dec 60 10 1meg")
    before = wrdata(body.replace("{R}", "1k"),  "mag(v(out))", "acb.txt")
    after = wrdata(body.replace("{R}", "2756.6"), "mag(v(out))", "aca.txt")
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.semilogx(before[:, 0], before[:, 1], color=GREY, lw=2, label="before  (R1 = 1 kΩ)")
    ax.semilogx(after[:, 0], after[:, 1], color=BLUE, lw=2, label="after  (R1 = 2757 Ω)")
    ax.plot([1e3], [0.5], "o", color=GREEN, ms=9, zorder=5)
    ax.annotate("target:\n|H| = 0.5 at 1 kHz", (1e3, 0.5), xytext=(3e3, 0.66),
                color=GREEN, arrowprops=dict(arrowstyle="->", color=GREEN))
    ax.set_xlabel("frequency  (Hz)"); ax.set_ylabel("|v(out)|")
    ax.set_title("Optimizer tunes R1 so the gain hits 0.5 at 1 kHz")
    ax.legend(loc="lower left"); ax.set_ylim(0, 1.05)
    fig.savefig(os.path.join(FIGS, "ac_response.png")); plt.close(fig)


# --------------------------------------------------------------- Fig 4: 2-D contour
def fig_contour_2d():
    R1 = np.linspace(500, 6000, 300)
    R2 = np.linspace(500, 6000, 300)
    G1, G2 = np.meshgrid(R1, R2)
    vout = G2 / (G1 + G2)
    itot = 1.0 / (G1 + G2)                          # |i(V1)|
    cost = (vout - 0.4) ** 2 + (itot - 0.2e-3) ** 2
    fig, ax = plt.subplots(figsize=(6.0, 4.6))
    cs = ax.contourf(G1, G2, np.log10(cost + 1e-16), levels=25, cmap="viridis")
    ax.plot([3000], [2000], "*", color="white", ms=18, mec="k", zorder=5)
    ax.annotate("found:\nR1 = 3 kΩ, R2 = 2 kΩ", (3000, 2000), xytext=(3300, 3400),
                color="white", arrowprops=dict(arrowstyle="->", color="white"))
    ax.set_xlabel("R1  (Ω)"); ax.set_ylabel("R2  (Ω)")
    ax.set_title("Two knobs: cost surface over (R1, R2)")
    fig.colorbar(cs, ax=ax, label="log10(cost)")
    fig.savefig(os.path.join(FIGS, "contour_2d.png")); plt.close(fig)


# ------------------------------------------------------------- Fig 5: transient
def fig_tran_response():
    body = ("rc step\nV1 in 0 dc 1\nR1 in out {R}\nC1 out 0 1u ic=0\n"
            ".tran 2u 1m uic")
    before = wrdata(body.replace("{R}", "1k"),    "v(out)", "trb.txt")
    after = wrdata(body.replace("{R}", "434.3"),  "v(out)", "tra.txt")
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.plot(before[:, 0] * 1e3, before[:, 1], color=GREY, lw=2, label="before  (R1 = 1 kΩ)")
    ax.plot(after[:, 0] * 1e3, after[:, 1], color=BLUE, lw=2, label="after  (R1 = 434 Ω)")
    ax.axhline(0.9, color=GREEN, ls="--", lw=1.2)
    ax.axvline(1.0, color=GREEN, ls="--", lw=1.2)
    ax.plot([1.0], [0.9], "o", color=GREEN, ms=9, zorder=5)
    ax.annotate("target:\n0.9 V at 1 ms", (1.0, 0.9), xytext=(0.45, 0.55),
                color=GREEN, arrowprops=dict(arrowstyle="->", color=GREEN))
    ax.set_xlabel("time  (ms)"); ax.set_ylabel("v(out)  (V)")
    ax.set_title("Optimizer tunes R1 so the step reaches 0.9 V at 1 ms")
    ax.legend(loc="lower right")
    fig.savefig(os.path.join(FIGS, "tran_response.png")); plt.close(fig)


# ------------------------------------------------------- Fig 6: OSDI diode I-V fit
def fig_osdi_diode():
    osdi = os.path.join(tempfile.gettempdir(), "optdiode.osdi")
    subprocess.run([VAF, os.path.join(OPT_EX, "optdiode.va"), "-o", osdi],
                   capture_output=True, text=True, timeout=120)

    def iv(is_val):
        body = (f"diode iv\nVd a 0 dc 0\nN1 a 0 dmod\n.model dmod optdiode is={is_val} n=1\n"
                f".control\npre_osdi {osdi}\ndc Vd 0 0.8 0.004\n"
                f"wrdata {{f}} abs(i(vd))\n.endc\n.end\n")
        tmp = os.path.join(tempfile.gettempdir(), "iv.txt")
        run(body.replace("{f}", tmp))
        d = np.array([[float(x) for x in ln.split()] for ln in open(tmp)
                      if ln.split() and ln.split()[0].replace('.', '', 1).replace('-', '', 1)[:1].isdigit()])
        os.remove(tmp)
        return d

    before = iv("1e-15")          # starting guess
    after = iv("1.2188e-14")      # fitted value
    os.remove(osdi)
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.semilogy(before[:, 0], np.abs(before[:, 1]), color=GREY, lw=2,
                label="before  (is = 1e-15)")
    ax.semilogy(after[:, 0], np.abs(after[:, 1]), color=BLUE, lw=2,
                label="after  (is = 1.22e-14, fitted)")
    ax.plot([0.65], [1e-3], "o", color=GREEN, ms=9, zorder=5)
    ax.annotate("measured point:\n1 mA at 0.65 V", (0.65, 1e-3), xytext=(0.10, 3e-3),
                color=GREEN, arrowprops=dict(arrowstyle="->", color=GREEN))
    ax.set_xlabel("diode voltage  (V)"); ax.set_ylabel("current  (A, log scale)")
    ax.set_title("Fitting a Verilog-A diode's is to a measured I–V point")
    ax.legend(loc="lower right"); ax.set_ylim(1e-9, 1e-1)
    fig.savefig(os.path.join(FIGS, "osdi_diode.png")); plt.close(fig)


# ------------------------------------------- Fig 7: least-squares LM vs NM (E-143)
def fig_lm_vs_nm():
    import math
    Rc, Cc = 2000.0, 100e-9
    H = [1.0 / math.sqrt(1.0 + (2 * math.pi * f * Rc * Cc) ** 2) for f in (500.0, 2000.0)]
    base = ("optimizer method compare\nV1 in 0 ac 1\nR1 in out 1k\nC1 out 0 100n\n"
            ".control\noptimize -param R1 1k 100 10k\n"
            f"+  -analysis ac lin 1 500 500   -target mag(v(out)) {H[0]:.10g}\n"
            f"+  -analysis ac lin 1 2000 2000 -target mag(v(out)) {H[1]:.10g}\n"
            "+  -method {M} -tol 1e-12 -maxiter 400 -verbose\n.endc\n.end\n")

    def trace(method, pat):
        out = run(base.replace("{M}", method))
        ev, cost = [], []
        for m in re.finditer(pat, out):
            cost.append(float(m.group(1))); ev.append(int(m.group(2)))
        return np.array(ev), np.array(cost)

    e_lm, c_lm = trace("lm", r"iter\s+\d+\s+cost\s+([-\d.eE+]+)\s+lambda\s+[-\d.eE+]+\s+\((\d+)\s+evals\)")
    e_nm, c_nm = trace("nm", r"iter\s+\d+\s+best cost\s+([-\d.eE+]+)\s+\((\d+)\s+evals\)")
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.semilogy(e_nm, np.maximum(c_nm, 1e-20), "o-", color=ORANGE, ms=4, lw=1.5,
                label=f"Nelder-Mead  ({e_nm[-1] if len(e_nm) else 0} evals)")
    ax.semilogy(e_lm, np.maximum(c_lm, 1e-20), "s-", color=BLUE, ms=5, lw=1.8,
                label=f"Levenberg-Marquardt  ({e_lm[-1] if len(e_lm) else 0} evals)")
    ax.set_xlabel("analysis evaluations"); ax.set_ylabel("sum-squared residual  (log scale)")
    ax.set_title("Least-squares fit: gradient LM reaches the optimum in fewer runs")
    ax.legend(loc="upper right")
    fig.savefig(os.path.join(FIGS, "lm_vs_nm.png")); plt.close(fig)


if __name__ == "__main__":
    for f in (fig_cost_bowl, fig_convergence, fig_ac_response,
              fig_contour_2d, fig_tran_response, fig_osdi_diode, fig_lm_vs_nm):
        f(); print("wrote", f.__name__)
    print("figures in", FIGS)
