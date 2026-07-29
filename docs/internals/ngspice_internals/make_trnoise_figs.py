#!/usr/bin/env python3
"""Figures for ngspice_transient_noise_analysis.md.

Every figure is produced from a simulation run here -- nothing is sketched. The
Verilog-A sources are written out, compiled with openvaf-r, and the resulting
waveforms are turned into spectra or variances and plotted against the closed
form derived in the document.

Usage:  python3 docs/internals/ngspice_internals/make_trnoise_figs.py
"""
import os
import re
import subprocess
import sys

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
OUT = os.path.join(HERE, "ngspice_trnoise_figs")
WORK = os.path.join(OUT, "_work")
NG = os.environ.get("NGSPICE_BIN", os.path.join(ROOT, "ngspice-46/build/src/ngspice"))


def find_vaf():
    for sub in ("macos/apple-silicon", "macos/intel", "linux/intel", "linux/arm"):
        p = os.path.join(ROOT, "bin", sub, "openvaf-r")
        if os.path.exists(p):
            return p
    return None


VAF = os.environ.get("OPENVAF_BIN") or find_vaf()

Q = 1.602176565e-19
K = 1.3806488e-23
T = 300.15
KT = K * T

FG = "#1b3a5c"
AC = "#c2492d"
GR = "#7a8b99"

VA = {
    "valin": """`include "disciplines.vams"
module valin(p, n);
  inout p, n;
  electrical p, n;
  parameter real r = 1e3 from (0:inf);
  parameter real c = 1e-9 from [0:inf);
  analog begin
    I(p, n) <+ V(p, n) / r;
    I(p, n) <+ ddt(c * V(p, n));
    I(p, n) <+ white_noise(4.0 * 1.3806488e-23 * $temperature / r, "thermal");
  end
endmodule
""",
    "vaflick": """`include "disciplines.vams"
module vaflick(p, n);
  inout p, n;
  electrical p, n;
  parameter real r = 1e3 from (0:inf);
  parameter real kf = 1e-20 from [0:inf);
  analog begin
    I(p, n) <+ V(p, n) / r;
    I(p, n) <+ flicker_noise(kf, 1.0, "fl");
  end
endmodule
""",
    "vadio": """`include "disciplines.vams"
module vadio(a, c);
  inout a, c;
  electrical a, c;
  parameter real is = 1e-14 from (0:inf);
  parameter real nf = 1.0 from (0:inf);
  real vt, id;
  analog begin
    vt = 1.3806488e-23 * $temperature / 1.602176565e-19;
    id = is * (exp(V(a, c) / (nf * vt)) - 1.0);
    I(a, c) <+ id;
    I(a, c) <+ white_noise(2.0 * 1.602176565e-19 * abs(id), "shot");
  end
endmodule
""",
}


def build_models():
    for name, src in VA.items():
        open(os.path.join(WORK, name + ".va"), "w").write(src)
        r = subprocess.run([VAF, name + ".va", "-o", name + ".osdi"], cwd=WORK,
                           capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            print("compile failed: %s\n%s" % (name, (r.stdout + r.stderr)[:400]))
            return False
    return True


def run(deck, tag, timeout=3600):
    p = os.path.join(WORK, "_%s.cir" % tag)
    open(p, "w").write(deck)
    r = subprocess.run([NG, "-b", "_%s.cir" % tag], cwd=WORK, capture_output=True,
                       text=True, timeout=timeout, errors="replace")
    return r.stdout + r.stderr


def wave(deck, out, vec, tag):
    p = os.path.join(WORK, out)
    if os.path.exists(p):
        os.remove(p)
    run(deck.replace("@WR@", "wrdata %s %s" % (out, vec)), tag)
    if not os.path.exists(p):
        return None, None
    d = np.loadtxt(p)
    return (d[:, 0], d[:, 1]) if d.ndim == 2 and len(d) > 64 else (None, None)


def psd(t, x, nseg=8):
    n = len(t)
    tu = np.linspace(t[0], t[-1], n)
    xu = np.interp(tu, t, x)
    dt = tu[1] - tu[0]
    seg = (n // nseg) // 2 * 2
    win = np.hanning(seg)
    acc = np.zeros(seg // 2 + 1)
    cnt = 0
    for i in range(nseg):
        s = xu[i * seg:(i + 1) * seg]
        if len(s) < seg:
            break
        s = s - s.mean()
        acc += np.abs(np.fft.rfft(s * win)) ** 2
        cnt += 1
    return np.fft.rfftfreq(seg, dt), 2 * acc / (cnt * (1 / dt) * np.sum(win ** 2))


def style(ax, xlabel, ylabel, title):
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.set_title(title, fontsize=10, color=FG)
    ax.tick_params(labelsize=8)
    ax.grid(True, which="both", alpha=0.25, lw=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


# ---------------------------------------------------------------- figure 1
def fig_white():
    """Built-in trnoise: measured PSD against the flat 2*NA^2*ts, and the
    sinc^4 rolloff that linear interpolation imposes near Nyquist."""
    NA, TS = 1e-3, 1e-8
    deck = """builtin trnoise
Vn n1 0 dc 0 trnoise({na} {ts} 0 0)
Rn n1 0 1meg
.control
option noacct
setseed 1
tran {ts} 400u 0 {ts}
@WR@
.endc
.end
""".format(na=NA, ts=TS)
    t, v = wave(deck, "w.dat", "v(n1)", "w")
    if t is None:
        return False
    f, p = psd(t, v, nseg=16)
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    m = f > 0
    ax.loglog(f[m], p[m], lw=0.6, color=GR, label="measured PSD")
    ax.axhline(2 * NA ** 2 * TS, color=AC, lw=1.6, ls="--",
               label=r"$2\,N_A^2\,t_s$ = %.2g V$^2$/Hz" % (2 * NA ** 2 * TS))
    fr = f[m]
    sinc = np.sinc(fr * TS) ** 4
    ax.loglog(fr, 2 * NA ** 2 * TS * sinc, color=FG, lw=1.2,
              label=r"$2N_A^2t_s\,\mathrm{sinc}^4(f t_s)$  (linear interpolation)")
    ax.axvline(1 / (2 * TS), color=FG, lw=0.8, ls=":", alpha=0.7)
    ax.text(1 / (2 * TS) * 0.30, 3.6e-14, "Nyquist\n$1/(2t_s)$", fontsize=7, color=FG,
            ha="center")
    ax.set_ylim(1e-16, 1e-13)
    style(ax, "frequency (Hz)", r"$S_v$ (V$^2$/Hz)",
          "Built-in trnoise source: white density and interpolation rolloff")
    ax.legend(fontsize=7.5, frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "trnoise_white_psd.png"), dpi=170)
    plt.close(fig)
    return True


# ---------------------------------------------------------------- figure 2
def fig_ktc():
    """kT/C is parameter-free: sweeping R must not move the variance."""
    C = 1e-9
    Rs = [500.0, 1e3, 5e3]
    seeds = range(1, 9)
    means, sds = [], []
    for r in Rs:
        vs = []
        for s in seeds:
            deck = """ktc
V1 in 0 dc 0
Rbig in mid 1g
N1 mid 0 mylin
.model mylin valin(r={r} c={c})
Vn nz 0 dc 0 trnoise(0 1e-8 0 0)
Rz nz 0 1k
.options reltol=1e-6 abstol=1e-18 vntol=1e-15
.control
option noacct
pre_osdi valin.osdi
setseed {s}
tran 1e-8 600u 0 1e-8
@WR@
.endc
.end
""".format(r=r, c=C, s=s)
            t, v = wave(deck, "k.dat", "v(mid)", "k")
            if t is not None:
                vs.append(np.var(v))
        means.append(np.mean(vs))
        sds.append(np.std(vs, ddof=1))
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    x = np.arange(len(Rs))
    ax.errorbar(x, np.array(means) * 1e12, yerr=np.array(sds) * 1e12, fmt="o",
                color=FG, capsize=5, ms=7, lw=1.4, label="measured (8 seeds, $\\pm$1 s.d.)")
    ax.axhline(KT / C * 1e12, color=AC, lw=1.8, ls="--",
               label=r"$kT/C$ = %.3f pV$^2$" % (KT / C * 1e12))
    ax.set_xticks(x)
    ax.set_xticklabels([r"$R$ = %g $\Omega$" % r for r in Rs], fontsize=9)
    ax.set_ylim(0, max(means) * 1e12 * 1.5)
    style(ax, "", r"var$\,[v]$  (pV$^2$)",
          "Thermal noise of an OSDI device: variance is $kT/C$, independent of $R$")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "trnoise_ktc.png"), dpi=170)
    plt.close(fig)
    return True


# ---------------------------------------------------------------- figure 3
def fig_shot():
    """Shot noise tracks the bias: var must follow 2qI * Rpar/(4C)."""
    REXT, C = 1e3, 1e-9
    VT = KT / Q
    bias = [0.50, 0.55, 0.60, 0.65, 0.70]
    Is, meas, theo = [], [], []
    for vb in bias:
        deck = """shot
V1 in 0 dc {vb}
Rs in mid {re}
N1 mid 0 mydio
Cx mid 0 {c}
.model mydio vadio(is=1e-14 nf=1)
Vn nz 0 dc 0 trnoise(0 1e-8 0 0)
Rz nz 0 1k
.options reltol=1e-6 abstol=1e-18 vntol=1e-15
.control
option noacct
pre_osdi vadio.osdi
op
let iq = i(v1)
echo IQ $&iq
setseed 3
tran 1e-8 600u 0 1e-8
@WR@
.endc
.end
""".format(vb=vb, re=REXT, c=C)
        p = os.path.join(WORK, "s.dat")
        if os.path.exists(p):
            os.remove(p)
        out = run(deck.replace("@WR@", "wrdata s.dat v(mid)"), "s")
        m = re.search(r"IQ\s+(-?[0-9.eE+-]+)", out)
        if not m or not os.path.exists(p):
            continue
        I = abs(float(m.group(1)))
        v = np.loadtxt(p)[:, 1]
        rd = VT / I
        Rp = 1 / (1 / rd + 1 / REXT)
        Is.append(I)
        meas.append(np.var(v))
        theo.append(2 * Q * I * Rp / (4 * C))
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    ax.loglog(Is, theo, "-", color=AC, lw=1.8, label=r"$2qI\,R_{\rm par}/(4C)$  (analytic)")
    ax.loglog(Is, meas, "o", color=FG, ms=7, label="measured transient variance")
    for I, mm, tt in zip(Is, meas, theo):
        ax.annotate("%.0f%%" % (100 * (mm / tt - 1)), (I, mm), textcoords="offset points",
                    xytext=(6, -11), fontsize=7, color=GR)
    style(ax, "diode current $I$ (A)", r"var$\,[v]$ (V$^2$)",
          "Shot noise on a nonlinear device: the density tracks the operating point")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "trnoise_shot.png"), dpi=170)
    plt.close(fig)
    return True


# ---------------------------------------------------------------- figure 4
def fig_flicker():
    """1/f shape, in the high-impedance regime where flicker dominates."""
    KF, r = 1e-20, 1e6
    deck = """flicker
V1 in 0 dc 0 ac 1
Rs in mid 1meg
N1 mid 0 myfl
.model myfl vaflick(r={r} kf={kf})
Vn nz 0 dc 0 trnoise(0 1e-6 0 0)
Rz nz 0 1k
.options reltol=1e-6 abstol=1e-18 vntol=1e-15
.control
option noacct
pre_osdi vaflick.osdi
setseed 1
tran 5e-6 0.2 0 5e-6
@WR@
.endc
.end
""".format(r=r, kf=KF)
    t, v = wave(deck, "f.dat", "v(mid)", "f")
    if t is None:
        return False
    f, p = psd(t, v, nseg=60)
    Rp = r / 2.0
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    m = (f > 20) & (f < 5e4)
    ax.loglog(f[m], p[m], lw=0.7, color=GR, label="measured PSD (60 Welch segments)")
    ax.loglog(f[m], KF * Rp ** 2 / f[m], color=AC, lw=1.8, ls="--",
              label=r"$k_f R_{\rm par}^2/f$  (analytic)")
    style(ax, "frequency (Hz)", r"$S_v$ (V$^2$/Hz)",
          "Flicker noise: measured spectrum follows $1/f$ at the predicted level")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "trnoise_flicker.png"), dpi=170)
    plt.close(fig)
    return True


def main():
    if not VAF or not os.path.exists(VAF):
        print("openvaf-r not found; set OPENVAF_BIN")
        return 2
    if not os.path.exists(NG):
        print("ngspice not found; set NGSPICE_BIN")
        return 2
    os.makedirs(WORK, exist_ok=True)
    if not build_models():
        return 1
    ok = True
    want = set(sys.argv[1:])          # regenerate one figure without redoing them all
    for name, fn in (("white", fig_white), ("ktc", fig_ktc),
                     ("shot", fig_shot), ("flicker", fig_flicker)):
        if want and name not in want:
            continue
        r = fn()
        print("  %-8s %s" % (name, "ok" if r else "FAILED"))
        ok &= bool(r)
    print("figures in %s" % OUT)
    return 0 if ok else 1


sys.exit(main())
