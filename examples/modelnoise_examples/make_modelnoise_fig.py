#!/usr/bin/env python3
"""Enhancement-165 figure: production compact-model noise.

Panel A -- BSIM4 output-noise spectral density Sv(f) of a common-source
amplifier: the OSDI-compiled model (markers) overlaid on ngspice's built-in
BSIM4 (line), log-log. The 1/f FLICKER region falls at low frequency; the flat
THERMAL floor sits at high frequency. The two models agree everywhere.

Panel B -- HICUM/L2 (SiGe HBT) output-noise floor vs collector current, with a
small source resistance so the intrinsic device noise dominates. The measured
floor (markers) tracks the collector SHOT-noise line 2q*Ic*RC^2 (dashed) across
two decades of bias -- the defining bipolar white-noise physics, for a model
ngspice has no built-in for.

Run:  python3 make_modelnoise_fig.py   ->  modelnoise.png
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
W = tempfile.mkdtemp(prefix="mnfig_")
Q = 1.602176634e-19
subprocess.run([OPENVAF, "bsim4.va", "-o", os.path.join(W, "bsim4.osdi")],
               cwd=os.path.join(ITEST, "BSIM4"), capture_output=True)
subprocess.run([OPENVAF, "hicuml2.va", "-o", os.path.join(W, "hicuml2.osdi")],
               cwd=os.path.join(ITEST, "HICUML2"), capture_output=True)


def run(deck):
    open(os.path.join(W, "d.cir"), "w").write(deck)
    return subprocess.run([NGSPICE, "-b", "d.cir"], cwd=W, capture_output=True, text=True).stdout


def dat(fn):
    return [[float(x) for x in l.split()] for l in open(os.path.join(W, fn))]


# --- Panel A: BSIM4 Sv(f) OSDI vs built-in ---
run("""* bsim4 noise
.control
pre_osdi bsim4.osdi
.endc
Vdd ddb 0 dc 1.8
RDb ddb db 10k
Vgb gb 0 dc 0.8 ac 1
M1 db gb 0 0 nb W=10u L=1u
.model nb nmos level=54 version=4.8.2 rdsmod=1 rsh=1
Vddo ddo 0 dc 1.8
RDo ddo do 10k
Vgo go 0 dc 0.8 ac 1
N1 do go 0 0 no
.model no bsim4va w=10u l=1u rdsmod=1 rsh=1
.control
noise v(db) Vgb dec 15 1 1e9
setplot noise1
wrdata b4b.dat onoise_spectrum
noise v(do) Vgo dec 15 1 1e9
setplot noise3
wrdata b4o.dat onoise_spectrum
.endc
.end
""")
b, o = dat("b4b.dat"), dat("b4o.dat")

# --- Panel B: HICUM floor vs Ic ---
ics, floors = [], []
for vbe in [0.70, 0.72, 0.74, 0.76, 0.78, 0.80, 0.82]:
    out = run(f"""* hicum shot
.control
pre_osdi hicuml2.osdi
.endc
Vcc cc 0 dc 3.0
RC cc c 400
Vsrc s 0 dc {vbe} ac 1
Rb s b 1
N1 c b 0 0 0 m
.model m hicumL2va t0=1e-11 cjei0=1f cjci0=1f cjep0=1f cjcx0=1f
.control
op
print abs(i(vcc))
noise v(c) Vsrc dec 2 1e4 1e5
setplot noise1
print onoise_spectrum[2]
.endc
.end
""")
    import re
    ic = float(re.search(r"i\(vcc\)\)\s*=\s*([-\d.eE+]+)", out).group(1))
    nf = float(re.search(r"onoise_spectrum\[2\]\s*=\s*([-\d.eE+]+)", out).group(1))
    ics.append(ic)
    floors.append(nf)

fig, (axA, axB) = plt.subplots(1, 2, figsize=(11, 4.4))

axA.loglog([r[0] for r in b], [r[1] for r in b], "-", color="#1f77b4", lw=2,
           label="built-in BSIM4")
axA.loglog([r[0] for r in o][::3], [r[1] for r in o][::3], "o", color="#1f77b4",
           ms=5, mfc="none", label="OSDI BSIM4")
axA.set_xlabel("frequency  [Hz]")
axA.set_ylabel(r"output noise  $\sqrt{S_v}$  [V/$\sqrt{\mathrm{Hz}}$]")
axA.set_title("A. BSIM4 noise: OSDI vs built-in")
axA.legend()
axA.grid(True, which="both", alpha=0.3)
axA.annotate("1/f flicker", xy=(3, sorted([r[1] for r in o])[-3]), fontsize=9, color="#555")
axA.annotate("thermal floor", xy=(3e7, o[-1][1] * 1.3), fontsize=9, color="#555")

icv = sorted(ics)
axB.loglog(ics, floors, "o", color="#d62728", ms=7, label="HICUM (OSDI)")
axB.loglog(icv, [math.sqrt(2 * Q * i * 400 ** 2) for i in icv], "k--", lw=1.5,
           label=r"collector shot  $\sqrt{2qI_C R_C^2}$")
axB.set_xlabel(r"collector current  $I_C$  [A]")
axB.set_ylabel(r"output noise floor  [V/$\sqrt{\mathrm{Hz}}$]")
axB.set_title("B. HICUM shot noise (no built-in reference)")
axB.legend()
axB.grid(True, which="both", alpha=0.3)

fig.tight_layout()
out = os.path.join(HERE, "modelnoise.png")
fig.savefig(out, dpi=110)
print("wrote", out)
