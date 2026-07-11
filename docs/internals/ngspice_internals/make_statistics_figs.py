#!/usr/bin/env python3
"""Generate the figures for ngspice_statistics.md from real ngspice runs.

Usage:  python3 docs/internals/ngspice_internals/make_statistics_figs.py
Writes PNGs into ngspice_statistics_figs/. Needs matplotlib + numpy and the
committed ngspice binary (which has mcsample / highsigma / mccorr / montecarlo).
"""
import os
import re
import subprocess
import tempfile

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import norm  # only for the analytic normal curves

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
FIGS = os.path.join(HERE, "ngspice_statistics_figs")
os.makedirs(FIGS, exist_ok=True)

NG = os.path.join(ROOT, "bin", "macos", "apple-silicon", "ngspice")
if not os.path.isfile(NG):
    NG = os.path.join(ROOT, "ngspice-46", "build", "src", "ngspice")

TMP = tempfile.mkdtemp(prefix="statfigs_")

BLUE, ORANGE, GREEN, RED, GREY = "#2563eb", "#ea7317", "#159947", "#cf222e", "#6b7280"
PURPLE = "#8250df"
plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.alpha": 0.3,
                     "figure.dpi": 130, "savefig.bbox": "tight"})


def run(deck):
    with open(os.path.join(TMP, "_f.cir"), "w") as f:
        f.write(deck)
    r = subprocess.run([NG, "-b", "_f.cir"], capture_output=True, text=True,
                       timeout=1800, cwd=TMP)
    return r.stdout + r.stderr


def grab(log, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)", log)
    return float(m.group(1)) if m else float("nan")


def read_cols(fname, ncol):
    cols = [[] for _ in range(ncol)]
    for ln in open(os.path.join(TMP, fname)):
        p = ln.split()
        if len(p) >= 1 + ncol and p[0].isdigit():
            try:
                for k in range(ncol):
                    cols[k].append(float(p[1 + k]))
            except ValueError:
                pass
    return [np.array(c) for c in cols]


def mc_samples(mode, n, seed=1, extra=""):
    """Return N drawn R values (R ~ N(1000, 33.333)) under the given mode."""
    cfg = {"random": f"mcsample random\n  setseed {seed}",
           "lhs": f"mcsample lhs {n} seed {seed}"}[mode]
    run(f"""* draw samples
.param rr = agauss(1000, 100, 3)
V1 a 0 DC 1
R1 a 0 {{rr}}
{extra}
.control
  set numdgt=10
  {cfg}
  let n = {n}
  let rv = unitvec(n)
  let run = 0
  dowhile run < n
    reset
    op
    let rv[run] = -1/i(v1)
    let run = run + 1
  end
  print rv > s.txt
.endc
.end
""")
    return read_cols("s.txt", 1)[0]


# ---------------------------------------------------------------- distribution
def fig_distribution():
    R = mc_samples("random", 5000, seed=3)
    mu, sig = 1000.0, 100.0 / 3.0
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.hist(R, bins=45, density=True, color=BLUE, alpha=0.55,
            edgecolor="white", label="5000 MC samples")
    x = np.linspace(mu - 4.5 * sig, mu + 4.5 * sig, 400)
    ax.plot(x, norm.pdf(x, mu, sig), color=RED, lw=2,
            label=r"analytic $N(1000,\,33.3)$")
    ax.set_xlabel(r"$R$  (from  agauss(1000, 100, 3),  $\sigma=100/3$)")
    ax.set_ylabel("density")
    ax.set_title("Monte Carlo distribution of a Gaussian .param")
    ax.legend(frameon=False)
    fig.savefig(os.path.join(FIGS, "distribution.png")); plt.close(fig)
    print("  distribution.png")


# ------------------------------------------------------------- LHS vs random
def fig_lhs():
    mu, sig = 1000.0, 100.0 / 3.0
    # (a) stratification: sorted samples vs their expected quantiles
    n = 24
    r_rnd = np.sort(mc_samples("random", n, seed=7))
    r_lhs = np.sort(mc_samples("lhs", n, seed=7))
    q = norm.ppf((np.arange(n) + 0.5) / n, mu, sig)
    # (b) variance of the mean estimate over trials
    M = 40
    def means(mode):
        return np.array([np.mean(mc_samples(mode, 32, seed=s)) for s in range(1, M + 1)])
    m_rnd, m_lhs = means("random"), means("lhs")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.2, 3.7))
    ax1.plot(q, r_rnd, "o", color=GREY, ms=6, label="random")
    ax1.plot(q, r_lhs, "o", color=BLUE, ms=6, label="Latin-Hypercube")
    lo, hi = q.min(), q.max()
    ax1.plot([lo, hi], [lo, hi], color=RED, lw=1.2, ls="--", label="ideal (= quantile)")
    ax1.set_xlabel("expected quantile"); ax1.set_ylabel("sorted sample")
    ax1.set_title(f"Stratification ({n} samples)")
    ax1.legend(frameon=False, fontsize=9)

    ax2.axhline(mu, color=RED, lw=1.2, ls="--", label="true mean")
    ax2.plot(np.zeros(M) + 0.0, m_rnd, "o", color=GREY, ms=5, alpha=0.7)
    ax2.plot(np.zeros(M) + 1.0, m_lhs, "o", color=BLUE, ms=5, alpha=0.7)
    ax2.set_xticks([0, 1]); ax2.set_xticklabels(["random", "LHS"])
    ax2.set_xlim(-0.5, 1.5)
    ax2.set_ylabel("estimated mean (N=32)")
    vr, vl = np.var(m_rnd), np.var(m_lhs)
    ax2.set_title(f"Estimator spread  (var {vr/vl:.0f}$\\times$ lower)")
    ax2.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "lhs_vs_random.png")); plt.close(fig)
    print("  lhs_vs_random.png")


# -------------------------------------------------------------- high-sigma
def fig_highsigma():
    mu, sig = 1000.0, 100.0 / 3.0
    betas = [2.0, 3.0, 4.0, 5.0, 6.0]
    est, estsig = [], []
    for b in betas:
        thr = mu + b * sig
        lam = 2.0 if b <= 3 else (2.6 if b <= 4 else 3.0)
        log = run(f"""* highsigma
.param rr = agauss(1000, 100, 3)
V1 a 0 DC 1
R1 a 0 {{rr}}
.control
  highsigma 8000 -scale {lam} -seed 1 -analysis op -metric -1/i(v1) -max {thr:.5f}
  print highsigma_pfail highsigma_sigma
.endc
.end
""")
        est.append(grab(log, "highsigma_pfail"))
        estsig.append(grab(log, "highsigma_sigma"))
    betas = np.array(betas); est = np.array(est)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.2, 3.7))
    bb = np.linspace(1.5, 6.5, 200)
    ax1.semilogy(bb, norm.sf(bb), color=RED, lw=2, label=r"analytic $\Phi(-\beta)$")
    ax1.semilogy(betas, est, "o", color=BLUE, ms=8, label="highsigma (8000 runs)")
    ax1.axhline(1e-4, color=GREY, ls=":", lw=1.2)
    ax1.text(1.6, 1.4e-4, "plain MC of 1e4 runs\ncannot resolve below here",
             fontsize=8, color=GREY, va="bottom")
    ax1.set_xlabel(r"spec margin  $\beta$  (sigmas)")
    ax1.set_ylabel("failure probability")
    ax1.set_title("High-sigma estimate vs analytic")
    ax1.legend(frameon=False, fontsize=9)

    # mechanism: nominal vs inflated density, failure region shaded
    z = np.linspace(-7, 7, 400)
    lam = 3.0
    ax2.plot(z, norm.pdf(z), color=BLUE, lw=2, label="nominal  N(0,1)")
    ax2.plot(z, norm.pdf(z, 0, lam), color=ORANGE, lw=2,
             label=f"inflated  N(0,{lam:.0f})")
    ax2.axvspan(5, 7, color=RED, alpha=0.15)
    ax2.text(5.05, 0.30, "failure\nregion\n($\\beta$=5)", fontsize=8, color=RED)
    ax2.set_xlabel("standardized parameter  z")
    ax2.set_ylabel("density")
    ax2.set_title("Scaled-sigma importance sampling")
    ax2.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "highsigma.png")); plt.close(fig)
    print("  highsigma.png")


# -------------------------------------------------------------- correlation
def fig_correlation():
    def draw(rho, n=2500, seed=1):
        run(f"""* correlated draws
.param a = mvnorm(1)
.param b = mvnorm(2)
V1 x 0 DC 1
Ra x 0 {{1000 + 100*a}}
V2 y 0 DC 1
Rb y 0 {{1000 + 100*b}}
.control
  set numdgt=8
  mccorr 2  1 {rho:g}  {rho:g} 1
  setseed {seed}
  let n = {n}
  let av = unitvec(n)
  let bv = unitvec(n)
  let run = 0
  dowhile run < n
    reset
    op
    let av[run] = (-1/i(v1) - 1000)/100
    let bv[run] = (-1/i(v2) - 1000)/100
    let run = run + 1
  end
  print av bv > c.txt
.endc
.end
""")
        return read_cols("c.txt", 2)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.0, 4.2), sharex=True, sharey=True)
    for ax, rho, col, ttl in ((ax1, 0.0, GREY, "independent  (rho = 0)"),
                              (ax2, 0.85, BLUE, "correlated  (rho = 0.85)")):
        a, b = draw(rho)
        emp = np.corrcoef(a, b)[0, 1]
        ax.plot(a, b, ".", color=col, ms=3, alpha=0.4)
        ax.set_title(f"{ttl}\nempirical corr = {emp:+.2f}", fontsize=10)
        ax.set_xlabel("param 1  (z)"); ax.axhline(0, color="k", lw=.5); ax.axvline(0, color="k", lw=.5)
        ax.set_xlim(-4, 4); ax.set_ylim(-4, 4); ax.set_aspect("equal")
    ax1.set_ylabel("param 2  (z)")
    fig.suptitle("Correlated process/mismatch draws  (mccorr + mvnorm)")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "correlation.png")); plt.close(fig)
    print("  correlation.png")


# -------------------------------------------------------------- yield vs corr
def fig_yield():
    # a matched resistor divider: v(out) = R2/(R1+R2). Correlated R1,R2 keep the
    # ratio at 0.5; independent R1,R2 let it wander. Spec: ratio in [0.48, 0.52].
    rhos = [0.0, 0.2, 0.4, 0.6, 0.8, 0.9, 0.95, 0.99]
    ys = []
    for rho in rhos:
        log = run(f"""* yield vs correlation (matched divider ratio)
.param r1 = 1000 + 50*mvnorm(1)
.param r2 = 1000 + 50*mvnorm(2)
V1 in 0 DC 1
R1 in out {{r1}}
R2 out 0 {{r2}}
.control
  mccorr 2  1 {rho:g}  {rho:g} 1
  montecarlo 4000 -lhs -seed 1 -analysis op -spec v(out) -max 0.52 -min 0.48
  print montecarlo_yield
.endc
.end
""")
        ys.append(100.0 * grab(log, "montecarlo_yield"))
    fig, ax = plt.subplots(figsize=(6.4, 3.7))
    ax.plot(rhos, ys, "o-", color=PURPLE, lw=2, ms=7)
    ax.axhline(ys[0], color=GREY, ls=":", lw=1.2)
    ax.text(0.02, ys[0] + 0.8, "independent (mismatch only)", fontsize=8, color=GREY)
    ax.set_xlabel(r"process correlation between $R_1$ and $R_2$   $\rho$")
    ax.set_ylabel("yield  (%)  of the $\\pm$4% ratio spec")
    ax.set_title("Yield of a matched divider rises with correlation")
    ax.set_ylim(min(ys) - 3, 101)
    fig.savefig(os.path.join(FIGS, "yield_vs_corr.png")); plt.close(fig)
    print("  yield_vs_corr.png")


if __name__ == "__main__":
    print("generating ngspice statistics figures...")
    fig_distribution()
    fig_lhs()
    fig_highsigma()
    fig_correlation()
    fig_yield()
    print("done ->", FIGS)
