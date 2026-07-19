#!/usr/bin/env python3
"""Generate the result plots for ngspice_commands.md from REAL ngspice runs.
Saves PNGs under ngspice_commands_figs/. Uses the committed ngspice binary and
only built-in device models, so every plot corresponds to a self-contained
netlist shown in the document.  Regenerate with:  python3 make_commands_figs.py
"""
import os, re, subprocess
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NG = os.environ.get("NGSPICE_BIN",
                    os.path.join(ROOT, "bin", "macos", "apple-silicon", "ngspice"))
if not os.path.exists(NG):
    NG = os.path.join(ROOT, "ngspice-46", "build", "src", "ngspice")
OUT = os.path.join(HERE, "ngspice_commands_figs")
os.makedirs(OUT, exist_ok=True)
WORK = os.path.join(OUT, "_work")
os.makedirs(WORK, exist_ok=True)

BLUE, RED, GREEN, GRAY, ORANGE = "#2b6cb0", "#c53030", "#2f855a", "#718096", "#dd6b20"
plt.rcParams.update({"font.size": 11, "axes.grid": True,
                     "grid.alpha": 0.35, "figure.dpi": 130,
                     "axes.spines.top": False, "axes.spines.right": False})


def run(deck, timeout=120):
    open(os.path.join(WORK, "_d.cir"), "w").write(deck)
    r = subprocess.run([NG, "-b", "_d.cir"], capture_output=True, text=True,
                       timeout=timeout, cwd=WORK)
    return r.stdout + r.stderr


def col(fname, ncol=2):
    """read a single-vector wrdata file (scale value per row)."""
    xs, ys = [], [[] for _ in range(ncol - 1)]
    for line in open(os.path.join(WORK, fname)):
        p = line.split()
        if len(p) >= ncol:
            try:
                vals = [float(v) for v in p[:ncol]]
            except ValueError:
                continue
            xs.append(vals[0])
            for i in range(ncol - 1):
                ys[i].append(vals[i + 1])
    return np.array(xs), [np.array(y) for y in ys]


def wr(fname, nvec):
    """read a MULTI-vector wrdata file. ngspice writes each vector prefixed by its
    own scale, so `wrdata f a b` -> columns [scale a scale b]. Return (x, [a,b,...])."""
    rows = []
    for line in open(os.path.join(WORK, fname)):
        p = line.split()
        if len(p) >= 2 * nvec:
            try:
                rows.append([float(v) for v in p[:2 * nvec]])
            except ValueError:
                pass
    a = np.array(rows)
    return a[:, 0], [a[:, 2 * i + 1] for i in range(nvec)]


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, name), bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


# ---------- 1. transient: RC step + RLC ring -----------------------------------
def fig_tran():
    run("""* transient: RC low-pass step + series RLC ring
Vin in 0 pulse(0 1 1u 1n 1n 1 2)
R1 in a 1k
C1 a 0 100n
L1 in b 1m
Rs b c 20
C2 c 0 100n
.tran 1u 400u
.control
run
wrdata tran.dat v(a) v(c)
.endc
.end
""")
    t, (va, vc) = wr("tran.dat", 2)
    fig, ax = plt.subplots(figsize=(7, 3.4))
    ax.plot(t * 1e6, va, color=BLUE, label="RC low-pass  v(a)")
    ax.plot(t * 1e6, vc, color=RED, label="series RLC  v(c)")
    ax.axhline(1.0, color=GRAY, ls="--", lw=0.8)
    ax.set_xlabel("time  [µs]"); ax.set_ylabel("voltage  [V]")
    ax.set_title("`.tran` — 1 V step into an RC (over-damped) and an RLC (ringing)")
    ax.legend(frameon=False)
    save(fig, "tran.png")


# ---------- 2. ac: RC low-pass Bode --------------------------------------------
def fig_ac():
    run("""* ac: RC low-pass Bode
Vin in 0 dc 0 ac 1
R1 in out 1k
C1 out 0 100n
.ac dec 40 1 1meg
.control
run
wrdata ac.dat vdb(out) vp(out)
.endc
.end
""")
    f, (mag, ph) = wr("ac.dat", 2)
    ph = ph * 180/np.pi if abs(ph).max() < 4 else ph   # vp() reports radians here
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7, 4.6), sharex=True)
    a1.semilogx(f, mag, color=BLUE)
    a1.axhline(-3, color=GRAY, ls="--", lw=0.8)
    a1.axvline(1/(2*np.pi*1e3*100e-9), color=RED, ls=":", lw=1, label="f₋₃dB ≈ 1.6 kHz")
    a1.set_ylabel("|H|  [dB]"); a1.legend(frameon=False)
    a1.set_title("`.ac` — RC low-pass frequency response (magnitude & phase)")
    a2.semilogx(f, ph, color=GREEN)
    a2.set_ylabel("phase  [deg]"); a2.set_xlabel("frequency  [Hz]")
    save(fig, "ac.png")


# ---------- 3. dc: diode I-V ---------------------------------------------------
def fig_dc_diode():
    run("""* dc: diode forward I-V
Vd a 0 dc 0
D1 a 0 DMOD
.model DMOD D(is=1e-14 n=1)
.dc Vd 0 0.8 0.005
.control
run
wrdata dcd.dat abs(i(vd))
.endc
.end
""")
    v, (i,) = col("dcd.dat", 2)
    fig, ax = plt.subplots(figsize=(7, 3.4))
    ax.semilogy(v, np.maximum(i, 1e-15), color=RED)
    ax.set_xlabel("V(anode)  [V]"); ax.set_ylabel("diode current  [A]")
    ax.set_title("`.dc` — diode forward characteristic (log I vs V)")
    save(fig, "dc_diode.png")


# ---------- 4. dc nested: NMOS output curves -----------------------------------
def fig_dc_mos():
    run("""* dc nested: NMOS Id-Vds family
Vds d 0 dc 0
Vgs g 0 dc 0
M1 d g 0 0 NM W=20u L=1u
.model NM NMOS(level=1 vto=0.7 kp=120u lambda=0.02)
.dc Vds 0 5 0.05 Vgs 1 4 1
.control
run
wrdata dcm.dat i(vds)
.endc
.end
""")
    # ngspice writes the swept curves concatenated; re-read with the inner sweep
    vds, (ids,) = col("dcm.dat", 2)
    fig, ax = plt.subplots(figsize=(7, 3.4))
    # split into segments where Vds resets to 0
    starts = [0] + [k for k in range(1, len(vds)) if vds[k] < vds[k-1]] + [len(vds)]
    for s, e, vg in zip(starts[:-1], starts[1:], [1, 2, 3, 4]):
        ax.plot(vds[s:e], -ids[s:e] * 1e3, label=f"Vgs = {vg} V")
    ax.set_xlabel("Vds  [V]"); ax.set_ylabel("Id  [mA]")
    ax.set_title("`.dc` (nested sweep) — NMOS output characteristics")
    ax.legend(frameon=False)
    save(fig, "dc_mos.png")


# ---------- 5. noise: output noise density -------------------------------------
def fig_noise():
    run("""* noise: RC + resistor thermal noise
Vin in 0 dc 0 ac 1
R1 in out 10k
C1 out 0 1n
.noise v(out) Vin dec 20 10 1meg
.control
run
setplot noise1
wrdata noise.dat onoise_spectrum
.endc
.end
""")
    f, (n,) = col("noise.dat", 2)
    fig, ax = plt.subplots(figsize=(7, 3.4))
    ax.loglog(f, n, color=ORANGE)
    ax.set_xlabel("frequency  [Hz]")
    ax.set_ylabel("output noise  [V/√Hz]")
    ax.set_title("`.noise` — output noise spectral density (10 kΩ + 1 nF)")
    save(fig, "noise.png")


# ---------- 6. fft: spectrum of a clipped sine ---------------------------------
def fig_fft():
    run("""* fft: harmonics of a diode-clipped sine
Vin in 0 sin(0 1.2 10k)
R1 in a 1k
D1 a 0 DL
D2 0 a DL
.model DL D(is=1e-12)
.tran 1u 2m
.control
run
linearize
fft v(a)
wrdata fft.dat mag(v(a))
.endc
.end
""")
    f, (m,) = col("fft.dat", 2)
    sel = f <= 120e3
    fig, ax = plt.subplots(figsize=(7, 3.4))
    ax.stem(f[sel] / 1e3, m[sel], basefmt=" ", linefmt=BLUE, markerfmt="o")
    ax.set_xlabel("frequency  [kHz]"); ax.set_ylabel("|V(a)|  [V]")
    ax.set_title("`fft` — spectrum of a diode-clipped 10 kHz sine (odd harmonics)")
    save(fig, "fft.png")


# ---------- 7. sp: S21 of an LC low-pass ---------------------------------------
def fig_sp():
    run("""* sp: LC low-pass S-parameters
L1 in out 1u
C1 out 0 400p
V1 in 0 dc 0 ac 1 portnum 1 z0 50
V2 out 0 dc 0 ac 1 portnum 2 z0 50
.sp dec 50 1meg 100meg
.control
run
wrdata sp.dat vdb(S_2_1)
.endc
.end
""")
    f, (s21,) = col("sp.dat", 2)
    fig, ax = plt.subplots(figsize=(7, 3.4))
    ax.semilogx(f, s21, color=BLUE, label="S21 (insertion gain)")
    ax.axhline(-3, color=GRAY, ls="--", lw=0.8, label="−3 dB")
    ax.set_xlabel("frequency  [Hz]"); ax.set_ylabel("|S21|  [dB]")
    ax.set_title("`.sp` — S-parameter S21 of an LC low-pass (50 Ω ports)")
    ax.legend(frameon=False, loc="lower left"); ax.set_ylim(-50, 5)
    save(fig, "sp.png")


# ---------- 8. pz: poles/zeros of an RLC in the complex plane -------------------
def fig_pz():
    out = run("""* pz: series RLC band-pass, poles & zeros of v(out)/i(in)
Vin in 0 dc 0 ac 1
L1 in m 1m
R1 m out 60
C1 out 0 100n
.pz in 0 out 0 vol pz
.control
run
print all
.endc
.end
""")
    poles, zeros = [], []
    for line in out.splitlines():
        m = re.search(r'pole\(\d+\)\s*=\s*([-\d.eE+]+),?\s*([-\d.eE+]+)?', line)
        z = re.search(r'zero\(\d+\)\s*=\s*([-\d.eE+]+),?\s*([-\d.eE+]+)?', line)
        if m:
            poles.append((float(m.group(1)), float(m.group(2) or 0)))
        if z:
            zeros.append((float(z.group(1)), float(z.group(2) or 0)))
    fig, ax = plt.subplots(figsize=(5.6, 3.8))
    if poles:
        pr, pi = zip(*poles)
        ax.scatter(np.array(pr)/1e3, np.array(pi)/1e3, marker="x", s=90,
                   color=RED, label="poles")
    if zeros:
        zr, zi = zip(*zeros)
        ax.scatter(np.array(zr)/1e3, np.array(zi)/1e3, marker="o", s=70,
                   facecolors="none", edgecolors=BLUE, label="zeros")
    ax.axhline(0, color=GRAY, lw=0.8); ax.axvline(0, color=GRAY, lw=0.8)
    ax.set_xlabel("Re  [krad/s]"); ax.set_ylabel("Im  [krad/s]")
    ax.set_title("`.pz` — poles (×) & zeros (o) of a series RLC")
    ax.legend(frameon=False, loc="upper right")
    save(fig, "pz.png")


if __name__ == "__main__":
    fig_tran()
    fig_ac()
    fig_dc_diode()
    fig_dc_mos()
    fig_noise()
    fig_fft()
    fig_sp()
    fig_pz()
    print("all figures written to", OUT)
