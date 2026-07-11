#!/usr/bin/env python3
"""Generate the RF-suite result plots for ngspice_rf_suite.md from REAL ngspice runs.
Saves PNGs under rf_figs/. Uses the committed ngspice binary and the rf_blocks OSDI
model. The PSS-shooting analyses (.pss/.pac/.pnoise) take minutes each; their data is
cached in rf_figs/*.dat once computed. Regenerate with:  python3 make_rf_figs.py
"""
import math, os, re, shutil, subprocess, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NG = os.path.join(ROOT, "bin", "macos", "apple-silicon", "ngspice")
OUT = os.path.join(HERE, "rf_figs")
os.makedirs(OUT, exist_ok=True)
WORK = os.path.join(OUT, "_work")
os.makedirs(WORK, exist_ok=True)
shutil.copy(os.path.join(ROOT, "examples", "rfanalyses_examples", "rf_blocks.osdi"), WORK)

kB, T, q = 1.380649e-23, 300.0, 1.602176634e-19
C1, R1 = 1e-9, 1e3          # the RC used across the linear PSS examples
BLUE, RED, GRAY = "#2b6cb0", "#c53030", "#94a3b8"


def run(deck, timeout=600):
    with open(os.path.join(WORK, "_d.cir"), "w") as f:
        f.write(deck)
    r = subprocess.run([NG, "-b", "_d.cir"], capture_output=True, text=True,
                       timeout=timeout, cwd=WORK)
    return r.stdout + r.stderr


def col(fname):
    x, y = [], []
    for line in open(os.path.join(WORK, fname)):
        p = line.split()
        if len(p) >= 2:
            try: x.append(float(p[0])); y.append(float(p[1]))
            except ValueError: pass
    return np.array(x), np.array(y)


def hb_table(out, node):
    """parse the `hb` harmonic table -> list of (harmonic, freq, |V|)."""
    rows = []
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 4 and p[0] == node:
            try:
                rows.append((int(p[1]), float(p[2]), float(p[3])))
            except ValueError:
                pass
    return rows


# ---------- 1. S-parameters: RC low-pass, built-in vs OSDI ---------------------
def fig_sp():
    run("""* S-params RC low-pass (built-in)
R1 in out 100
C1 out 0 1n
V1 in 0 DC 0 AC 1 portnum 1 z0 50
V2 out 0 DC 0 AC 1 portnum 2 z0 50
.sp dec 30 100k 1g
.control
run
wrdata sp_b.dat vdb(S_2_1)
.endc
.end
""")
    run("""* S-params RC low-pass (OSDI)
.control
pre_osdi rf_blocks.osdi
.endc
N1 in out mm
.model mm ores r=100
N2 out 0 mmc
.model mmc ocap cap=1n
V1 in 0 DC 0 AC 1 portnum 1 z0 50
V2 out 0 DC 0 AC 1 portnum 2 z0 50
.sp dec 30 100k 1g
.control
run
wrdata sp_o.dat vdb(S_2_1)
.endc
.end
""")
    fb, sb = col("sp_b.dat"); fo, so = col("sp_o.dat")
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.semilogx(fb, sb, color=BLUE, lw=2.4, label="built-in R + C")
    ax.semilogx(fo, so, "--", color=RED, lw=1.6, label="OSDI ores + ocap")
    ax.axhline(-6.02, color=GRAY, ls=":", lw=1)
    ax.axvline(1/(2*math.pi*100*1e-9), color=GRAY, ls=":", lw=1)
    ax.annotate("−6.02 dB  (50Ω→100Ω→50Ω divider)", (1.3e5, -5.2), fontsize=8, color="#555")
    ax.annotate("corner  1/(2πRC) ≈ 1.6 MHz", (2e6, -9), fontsize=8, color="#555")
    ax.set_xlabel("frequency (Hz)"); ax.set_ylabel("|S21|  (dB)")
    ax.set_title("S-parameters — RC low-pass  (.sp): built-in and OSDI agree")
    ax.grid(alpha=.3, which="both"); ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_sp.png"), dpi=120); plt.close(fig)
    print("fig_sp done")


# ---------- 2. Harmonic Balance: cubic (built-in) + diode (OSDI) ---------------
def fig_hb():
    ob = run("""* HB cubic nonlinearity (built-in)
I1 0 n SIN(0 0.1m 100meg)
R1 n 0 1k
Bnl n 0 I = 0.5e-3*V(n)*V(n)*V(n)
.options numdgt=8
.control
hb 100meg 6
.endc
.end
""")
    oo = run("""* HB OSDI diode
.control
pre_osdi rf_blocks.osdi
.endc
V1 a 0 SIN(0 0.6 100meg)
R1 a b 1k
N1 b 0 dd
.model dd odio is_=1e-14
.control
pre_osdi rf_blocks.osdi
hb 100meg 6
.endc
.end
""")
    hb = hb_table(ob, "n"); ho = hb_table(oo, "b")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.6, 3.9))
    for ax, rows, ttl, cavg in ((a1, hb, "cubic B-source (built-in)\nI = 0.5m·V³", BLUE),
                                (a2, ho, "OSDI diode (Verilog-A)\nodio, is=1e-14", RED)):
        ks = [r[0] for r in rows]; mags = [max(r[2], 1e-18) for r in rows]
        ax.bar(ks, mags, color=cavg, width=.6)
        ax.set_yscale("log"); ax.set_xlabel("harmonic index k  (freq = k·100 MHz)")
        ax.set_ylabel("|V_k|  (V)"); ax.set_title(ttl, fontsize=10)
        ax.grid(alpha=.3, axis="y")
    fig.suptitle("Harmonic Balance (hb): steady-state harmonic spectrum", y=1.02)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_hb.png"), dpi=120, bbox_inches="tight"); plt.close(fig)
    print("fig_hb done  builtin_harmonics=%d osdi_harmonics=%d" % (len(hb), len(ho)))


# ---------- 3. QPSS two-tone: IM3 ---------------------------------------------
def fig_qpss():
    out = run("""* QPSS two-tone -> IM3
V1 n1 0 SIN(0 0.1 100meg)
V2 n2 n1 SIN(0 0.1 110meg)
Rhi n2 0 1meg
Bout out 0 V = 0.5*V(n2)*V(n2)*V(n2)
Rout out 0 1k
.control
qpss v(out) 100meg 110meg 4 3
.endc
.end
""")
    pts = []
    for line in out.splitlines():
        m = re.search(r"\(\s*(-?\d+),\s*(-?\d+)\)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)", line)
        if m:
            f = float(m.group(3)); v = float(m.group(4))
            if f > 0 and v > 1e-9:
                pts.append((f, v, int(m.group(1)), int(m.group(2))))
    fig, ax = plt.subplots(figsize=(7.6, 4.0))
    for f, v, k1, k2 in pts:
        ax.plot([f/1e6, f/1e6], [1e-9, v], color=GRAY, lw=1)
        ax.plot(f/1e6, v, "o", color=BLUE, ms=5)
        lbl = {(1,0): "f1", (0,1): "f2", (2,-1): "2f1−f2\n(IM3)", (-1,2): "2f2−f1\n(IM3)"}.get((k1,k2))
        if lbl:
            ax.annotate(lbl, (f/1e6, v*1.4), fontsize=8, ha="center",
                        color=RED if "IM3" in lbl else "#333")
    ax.set_yscale("log"); ax.set_xlabel("frequency (MHz)"); ax.set_ylabel("|V|  (V)")
    ax.set_title("Two-tone QPSS (qpss): intermodulation spectrum through a cubic")
    ax.set_xlim(80, 130); ax.grid(alpha=.3, which="both")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_qpss.png"), dpi=120); plt.close(fig)
    print("fig_qpss done  products=%d" % len(pts))


# ---------- 4. Oscillator phase noise -----------------------------------------
def fig_phasenoise():
    out = run("""* LC oscillator phase noise
L1 n 0 1u
C1 n 0 1n
Bnl 0 n I = 2m*V(n) - 5m*V(n)*V(n)*V(n)
R1 n 0 100k
.ic V(n)=0.1
.control
hbosc n 5 5.0329meg 60u
phasenoise 1k 10meg 5
.endc
.end
""")
    off, L = [], []
    for line in out.splitlines():
        m = re.match(r"\s*([0-9.eE+]+)\s+(-?[0-9.eE+]+)\s*$", line)
        if m:
            f = float(m.group(1)); l = float(m.group(2))
            if 1 <= f <= 2e7 and -400 < l < 50:
                off.append(f); L.append(l)
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    ax.semilogx(off, L, "o-", color=BLUE, ms=4, lw=1.8, label="phasenoise L(Δf)")
    if len(off) > 2:
        f0 = off[len(off)//3]; L0 = L[len(off)//3]
        ff = np.array(sorted(off))
        ax.semilogx(ff, L0 - 20*np.log10(ff/f0), "--", color=RED, lw=1.3, label="−20 dB/decade")
    ax.set_xlabel("offset frequency Δf (Hz)"); ax.set_ylabel("L(Δf)  (dBc/Hz)")
    ax.set_title("Oscillator phase noise (hbosc + phasenoise): the 1/Δf² skirt")
    ax.grid(alpha=.3, which="both"); ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_phasenoise.png"), dpi=120); plt.close(fig)
    print("fig_phasenoise done  points=%d" % len(off))


# ---------- 5. Envelope following: high-Q tank --------------------------------
def fig_envelope():
    fc = 5.032921e6; Tp = 1/fc
    run(f"""* envelope high-Q tank
v1 s 0 sin(0 1 {fc:.6e})
l1 s a 1u
c1 a 0 1n
r1 a 0 100k
.control
envelope a {fc:.6e} 596u
wrdata env.dat a_amp
.endc
.end
""")
    run(f"""* tran reference
v1 s 0 sin(0 1 {fc:.6e})
l1 s a 1u
c1 a 0 1n
r1 a 0 100k
.control
tran {Tp/128:.6e} 596u
wrdata env_tr.dat v(a)
.endc
.end
""")
    et, ea = col("env.dat"); tt, vv = col("env_tr.dat")
    def fund(tc):
        m = (tt >= tc) & (tt < tc + Tp)
        if m.sum() < 8: return None
        t = tt[m]; v = vv[m]; w = 2*math.pi*fc*(t-tc)
        return 2*math.hypot(np.trapezoid(v*np.cos(w), t)/Tp, -np.trapezoid(v*np.sin(w), t)/Tp)
    env_t = [k*20*Tp for k in range(int(596e-6/(20*Tp)))]
    env_a = [fund(tc) for tc in env_t]
    fig, ax = plt.subplots(figsize=(7.6, 4.0))
    ax.plot([t*1e6 for t in env_t], env_a, "-", color=GRAY, lw=2.2, label="full transient amplitude 2|V1|")
    ax.plot(et*1e6, ea, "o", color=RED, ms=5, label=f"envelope samples ({len(et)} pts)")
    ax.set_xlabel("time (µs)"); ax.set_ylabel("amplitude 2|V1|(a)  (V)")
    ax.set_title("Envelope following (envelope): Q≈3160 tank ring-up, 26 samples ≈ 3000 periods")
    ax.set_ylim(bottom=0); ax.grid(alpha=.3); ax.legend(loc="lower right")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_envelope.png"), dpi=120); plt.close(fig)
    print("fig_envelope done  samples=%d" % len(et))


# ---------- 6-8. PSS / PAC / Pnoise on the linear RC (slow: cached) ------------
def ensure_pss_data():
    need = {
      "pss_rc.dat": """* PSS periodic steady state (linear RC)
V1 a 0 SIN(0 1 1meg)
R1 a b 1k
C1 b 0 1n
.pss 1meg 1u b 512 8 40 5u
.control
run
wrdata pss_rc.dat b
.endc
.end
""",
      "pac_rc.dat": """* PAC (linear RC)
V1 a 0 SIN(0 1 1meg)
R1 a b 1k
C1 b 0 1n
.pac 1meg 1u b 512 8 40 5u dec 15 10k 10meg
.control
run
wrdata pac_rc.dat mag(b)
.endc
.end
""",
      "pnoise_rc.dat": """* Pnoise (linear RC)
V1 a 0 DC 0 AC 1 SIN(0 1 1meg)
R1 a b 1k
C1 b 0 1n
.pnoise 1meg 1u b 512 8 40 5u b v1 dec 15 10k 10meg
.control
run
wrdata pnoise_rc.dat onoise_spectrum
.endc
.end
""",
    }
    for fn, deck in need.items():
        if not os.path.exists(os.path.join(WORK, fn)):
            print("  (running slow PSS deck for %s ...)" % fn); run(deck, timeout=900)


def fig_pss():
    f, v = col("pss_rc.dat")
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    ax.plot(f*1e6, v, color=BLUE, lw=2)
    ax.set_xlabel("time within one period (µs)"); ax.set_ylabel("v(b)  (V)")
    ax.set_title("Periodic steady state (.pss): node b over one 1 µs period")
    ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_pss.png"), dpi=120); plt.close(fig)
    print("fig_pss done")


def fig_pac():
    f, mag = col("pac_rc.dat")
    Z = 1.0/np.abs(1/R1 + 1j*2*np.pi*f*C1)
    fig, ax = plt.subplots(figsize=(7.2, 3.9))
    ax.loglog(f, mag, "o", color=RED, ms=5, label=".pac sideband-0 |v(b)|")
    ax.loglog(f, Z, "-", color=BLUE, lw=1.8, label="analytic |Z| = 1/|1/R+jωC|")
    ax.set_xlabel("input frequency (Hz)"); ax.set_ylabel("|response|  (Ω per A, i.e. V)")
    ax.set_title("Periodic AC (.pac): reduces exactly to the RC driving-point impedance")
    ax.grid(alpha=.3, which="both"); ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_pac.png"), dpi=120); plt.close(fig)
    print("fig_pac done")


def fig_pnoise():
    f, on = col("pnoise_rc.dat")
    Svv = 4*kB*T*R1 / (1 + (2*np.pi*f*R1*C1)**2)      # PSD in V^2/Hz
    fig, ax = plt.subplots(figsize=(7.2, 3.9))
    ax.loglog(f, on, "o", color=RED, ms=5, label=".pnoise onoise_spectrum (PSD)")
    ax.loglog(f, Svv, "-", color=BLUE, lw=1.8, label="analytic 4kTR/(1+(ωRC)²)")
    ax.axhline(4*kB*T*R1, color=GRAY, ls=":", lw=1)
    ax.annotate("4kTR ≈ 1.66e−17 V²/Hz  (1kΩ Johnson noise)", (1.2e4, 4*kB*T*R1*1.15),
                fontsize=8, color="#555")
    ax.set_xlabel("frequency (Hz)"); ax.set_ylabel("output noise PSD (V²/Hz)")
    ax.set_title("Periodic noise (.pnoise): reduces exactly to RC-shaped thermal noise")
    ax.grid(alpha=.3, which="both"); ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_pnoise.png"), dpi=120); plt.close(fig)
    print("fig_pnoise done")


if __name__ == "__main__":
    todo = sys.argv[1:] or ["sp", "hb", "qpss", "phasenoise", "envelope", "pss", "pac", "pnoise"]
    if any(x in todo for x in ("pss", "pac", "pnoise")):
        ensure_pss_data()
    fns = {"sp": fig_sp, "hb": fig_hb, "qpss": fig_qpss, "phasenoise": fig_phasenoise,
           "envelope": fig_envelope, "pss": fig_pss, "pac": fig_pac, "pnoise": fig_pnoise}
    for k in todo:
        try: fns[k]()
        except Exception as e: print("FAILED", k, "->", repr(e))
