#!/usr/bin/env python3
"""Enhancement-168 figure: noise figure of an LNA.

Panel A -- NOISE MATCH. The noise figure of a common-emitter HICUM/L2 LNA versus
source resistance Rs (markers), the classic U-curve with an optimum source
resistance Rs_opt. The two dashed asymptotes -- the amplifier's input VOLTAGE
noise en (dominating at small Rs) and its input CURRENT noise in (the base SHOT
noise, dominating at large Rs) -- cross near the minimum, showing why an LNA has
an optimum source impedance. en and in are extracted from the measured curve.

Panel B -- FRIIS CASCADE. Noise figure of a two-stage cascade versus the first
stage's available power gain G1 (set by its collector load). The measured
F_total (markers) tracks the Friis prediction F1 + (F2-1)/G1 (line) and collapses
onto the first stage's own NF F1 (dashed) as G1 grows -- the first-stage-
dominance principle that makes the front-end LNA set the system noise figure.

Run:  python3 make_noisefigure_fig.py   ->  noisefigure.png
"""
import math
import os
import subprocess
import sys
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

ITEST = os.path.join(ROOT, "OpenVAF-master-20260610", "integration_tests")
W = tempfile.mkdtemp(prefix="nffig_")
K = 1.380649e-23; Q = 1.602176634e-19; T0 = 290.0; FOURKT = 4 * K * T0
FMID = 1e8; IB = 20e-6
subprocess.run([OPENVAF, "hicuml2.va", "-o", os.path.join(W, "hicuml2.osdi")],
               cwd=os.path.join(ITEST, "HICUML2"), capture_output=True)

HEAD = """.options temp=16.85
.control
pre_osdi hicuml2.osdi
.endc
"""
MODEL = ".model m hicumL2va t0=1e-11 cjei0=1f cjci0=1f cjep0=1f cjcx0=1f\n"


def run(deck):
    open(os.path.join(W, "d.cir"), "w").write(deck)
    subprocess.run([NGSPICE, "-b", "d.cir"], cwd=W, capture_output=True, text=True)


def dat(fn):
    return [[float(x) for x in l.split()] for l in open(os.path.join(W, fn))]


def at(rows, f):
    return min(rows, key=lambda r: abs(r[0] - f))[1]


def nf_single(Rs, RC):
    run(f"""* single
{HEAD}Vsrc s 0 dc 0 ac 1
Rs s in {Rs}
Cin in b 1u
Ib 0 b dc {IB}
Vcc cc 0 dc 3.0
RC cc c {RC}
N1 c b 0 0 0 m
{MODEL}.noise v(c) Vsrc dec 3 8e7 1.2e8
.control
run
setplot noise1
wrdata n.dat inoise_spectrum
.endc
.end
""")
    ino = at(dat("n.dat"), FMID)
    return 10 * math.log10(ino ** 2 / (FOURKT * Rs)), ino


def gain_avail(Rs, RC):
    run(f"""* gain
{HEAD}Vsrc s 0 dc 0 ac 1
Rs s in {Rs}
Cin in b 1u
Ib 0 b dc {IB}
Vcc cc 0 dc 3.0
RC cc c {RC}
N1 c b 0 0 0 m
{MODEL}.ac dec 3 8e7 1.2e8
.control
run
wrdata g.dat vm(c)
.endc
.end
""")
    return at(dat("g.dat"), FMID) ** 2 * Rs / RC


def nf_two(RC1):
    run(f"""* two
{HEAD}Vsrc s 0 dc 0 ac 1
Rs s in 200
Cin in b1 1u
Ib1 0 b1 dc {IB}
Vcc cc 0 dc 3.0
RC1 cc c1 {RC1}
N1 c1 b1 0 0 0 m
Cc c1 b2 1u
Ib2 0 b2 dc {IB}
RC2 cc c2 1k
N2 c2 b2 0 0 0 m
{MODEL}.noise v(c2) Vsrc dec 5 1e7 1e9
.control
run
setplot noise1
wrdata t.dat inoise_spectrum
.endc
.end
""")
    return 10 * math.log10(at(dat("t.dat"), FMID) ** 2 / (FOURKT * 200))


# --- Panel A: NF vs Rs + asymptotes ---
RSS = [20, 33, 50, 75, 100, 150, 200, 300, 500, 750, 1000, 1500, 2000, 3300, 5000]
rs_nf, rs_ino = [], []
for rs in RSS:
    nfdb, ino = nf_single(rs, 1000)
    rs_nf.append(nfdb); rs_ino.append(ino)
# fit inoise^2 - 4kT Rs = en^2 + in^2 Rs^2
X = [rs ** 2 for rs in RSS]; Y = [i ** 2 - FOURKT * rs for rs, i in zip(RSS, rs_ino)]
n = len(X); sx = sum(X); sy = sum(Y); sxx = sum(x * x for x in X); sxy = sum(x * y for x, y in zip(X, Y))
in2 = (n * sxy - sx * sy) / (n * sxx - sx * sx); en2 = (sy - in2 * sx) / n
en, i_n = math.sqrt(max(en2, 0)), math.sqrt(in2)
rs_opt = en / i_n
imin = min(range(len(RSS)), key=lambda k: rs_nf[k])

# --- Panel B: NF vs first-stage gain (Friis) ---
RC1S = [50, 100, 200, 400, 800, 1600, 3200]
g1s, ftot, f1s, fried = [], [], [], []
for rc1 in RC1S:
    f1, _ = nf_single(200, rc1)
    f2, _ = nf_single(rc1, 1000)          # stage-2 source impedance ~= RC1
    g1 = gain_avail(200, rc1)
    ft = nf_two(rc1)
    F1, F2 = 10 ** (f1 / 10), 10 ** (f2 / 10)
    g1s.append(g1); ftot.append(ft); f1s.append(f1)
    fried.append(10 * math.log10(F1 + (F2 - 1) / g1))

# ----------------------------- plot -------------------------------------------
fig, (axA, axB) = plt.subplots(1, 2, figsize=(13, 5.2))
C1, C2, C3 = "#1f77b4", "#d62728", "#2ca02c"

axA.semilogx(RSS, rs_nf, "o", color=C1, ms=7, label="LNA noise figure (measured)")
rsl = [r for r in [10 * 1.3 ** k for k in range(30)] if 15 <= r <= 6000]
axA.semilogx(rsl, [10 * math.log10(1 + en2 / (FOURKT * r)) for r in rsl], "--",
             color=C3, lw=1.3, label=r"voltage-noise limit  $e_n^2/4kTR_s$")
axA.semilogx(rsl, [10 * math.log10(1 + in2 * r / FOURKT) for r in rsl], "--",
             color=C2, lw=1.3, label=r"current(shot)-noise limit  $i_n^2 R_s/4kT$")
axA.plot(RSS[imin], rs_nf[imin], "*", color="k", ms=16, zorder=5)
axA.annotate(f"$R_{{s,opt}}\\approx{RSS[imin]}\\,\\Omega$\nNF$_{{min}}$={rs_nf[imin]:.2f} dB",
             xy=(RSS[imin], rs_nf[imin]), xytext=(RSS[imin] * 1.3, rs_nf[imin] + 0.9),
             fontsize=9, ha="left")
axA.set_xlabel(r"source resistance  $R_s$  [$\Omega$]")
axA.set_ylabel("noise figure  NF  [dB]")
axA.set_title("A. noise match: optimum source resistance")
axA.set_ylim(0, 6)
axA.legend(fontsize=8.5, loc="upper center")
axA.grid(True, which="both", alpha=0.3)
axA.text(0.02, 0.02, f"extracted  $e_n$={en*1e9:.2f} nV/$\\sqrt{{Hz}}$,  "
         f"$i_n$={i_n*1e12:.2f} pA/$\\sqrt{{Hz}}$\n"
         f"($i_n$ = base shot $\\sqrt{{2qI_B}}$={math.sqrt(2*Q*IB)*1e12:.2f} pA/$\\sqrt{{Hz}}$)",
         transform=axA.transAxes, fontsize=8, va="bottom",
         bbox=dict(boxstyle="round", fc="white", ec="#ccc", alpha=0.9))

order = sorted(range(len(g1s)), key=lambda k: g1s[k])
gx = [g1s[k] for k in order]
axB.semilogx(gx, [ftot[k] for k in order], "o", color=C1, ms=8, label="$F_{total}$ measured")
axB.semilogx(gx, [fried[k] for k in order], "-", color=C2, lw=1.6,
             label=r"Friis  $F_1+(F_2-1)/G_1$")
axB.semilogx(gx, [f1s[k] for k in order], "--", color="#888", lw=1.3,
             label="$F_1$ (first stage alone)")
axB.set_xlabel(r"first-stage available power gain  $G_1$")
axB.set_ylabel("cascade noise figure  [dB]")
axB.set_title("B. Friis cascade: first-stage dominance")
axB.legend(fontsize=9, loc="upper right")
axB.grid(True, which="both", alpha=0.3)
axB.annotate("high gain -> $F_{total}\\to F_1$\n(front-end sets system NF)",
             xy=(gx[-1], ftot[order[-1]]), xytext=(gx[-1] * 0.15, ftot[order[-1]] + 0.35),
             fontsize=8.5, ha="left",
             arrowprops=dict(arrowstyle="->", color="#555"))

fig.suptitle("Noise figure of an LNA built from a Verilog-A/OSDI compact model "
             "(HICUM/L2) -- Enhancement-168", fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.95])
out = os.path.join(HERE, "noisefigure.png")
fig.savefig(out, dpi=110)
print("wrote", out)
