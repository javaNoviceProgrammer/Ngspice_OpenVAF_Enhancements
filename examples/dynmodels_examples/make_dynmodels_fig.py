#!/usr/bin/env python3
"""Enhancement-161 figure: dynamic (AC/RF) compact-model validation.

Panel A -- BSIM4 gate C-V: Cgg(Vgs) extracted from .ac, OSDI (markers) overlaid on
ngspice's built-in BSIM4 (line). The rise from a small subthreshold value to the
oxide capacitance in inversion is the textbook MOSFET C-V; the two agree to <1%.

Panel B -- AC current gain |h21| vs frequency for BSIM4 (MOSFET) and HICUML2 (SiGe
HBT). The -20 dB/decade roll-off and the crossing of |h21|=1 define the cutoff
frequency fT (~3.5 GHz for the MOSFET, ~15.5 GHz for the HBT at its transit-time
limit). OSDI (markers) tracks the built-in MOSFET (line).

Run:  python3 make_dynmodels_fig.py   ->  dynmodels_ac.png
"""
import math
import os
import re
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
W = tempfile.mkdtemp(prefix="dynfig_")
subprocess.run([OPENVAF, "bsim4.va", "-o", os.path.join(W, "bsim4.osdi")],
               cwd=os.path.join(ITEST, "BSIM4"), capture_output=True)
subprocess.run([OPENVAF, "hicuml2.va", "-o", os.path.join(W, "hicuml2.osdi")],
               cwd=os.path.join(ITEST, "HICUML2"), capture_output=True)


def run(deck, dat):
    open(os.path.join(W, "f.cir"), "w").write(deck)
    subprocess.run([NGSPICE, "-b", "f.cir"], cwd=W, capture_output=True, text=True)
    return [[float(x) for x in l.split()] for l in open(os.path.join(W, dat)) if l.split()]


# --- Panel A data: Cgg vs Vgs ---
vgs = [i * 0.05 for i in range(25)]
cb, co = [], []
for vg in vgs:
    r = run(f"""* cv
.control
pre_osdi bsim4.osdi
.endc
Vgb gb 0 dc {vg} ac 1
Vdb db 0 dc 0.05
M1 db gb 0 0 nb W=10u L=1u
.model nb nmos level=54 version=4.8.2 rdsmod=1 rsh=1
Vgo go 0 dc {vg} ac 1
Vdo do 0 dc 0.05
N1 do go 0 0 no
.model no bsim4va w=10u l=1u rdsmod=1 rsh=1
.ac lin 1 1meg 1meg
.control
run
let w=2*pi*1e6
wrdata cv.dat abs(imag(i(vgb)))/w*1e15 abs(imag(i(vgo)))/w*1e15
.endc
.end
""", "cv.dat")
    cb.append(r[0][1])
    co.append(r[0][3])

# --- Panel B data: h21(f) for BSIM4 (MOSFET) and HICUML2 (HBT) ---
b4 = run("""* bsim4 h21
.control
pre_osdi bsim4.osdi
.endc
Vgb gb 0 dc 1.0 ac 1
Vdb db 0 dc 0.6
M1 db gb 0 0 nb W=10u L=1u
.model nb nmos level=54 version=4.8.2 rdsmod=1 rsh=1
Vgo go 0 dc 1.0 ac 1
Vdo do 0 dc 0.6
N1 do go 0 0 no
.model no bsim4va w=10u l=1u rdsmod=1 rsh=1
.ac dec 15 1e7 2e10
.control
run
wrdata b4.dat abs(i(vdb)/i(vgb)) abs(i(vdo)/i(vgo))
.endc
.end
""", "b4.dat")
hb = run("""* hicum h21
.control
pre_osdi hicuml2.osdi
.endc
Vc c 0 dc 1.5
Vb b 0 dc 0.85 ac 1
N1 c b 0 0 0 m
.model m hicumL2va t0=1e-11 cjei0=1f cjci0=1f cjep0=1f cjcx0=1f
.ac dec 15 1e8 1e11
.control
run
wrdata hb.dat abs(i(vc)/i(vb))
.endc
.end
""", "hb.dat")

fig, (axA, axB) = plt.subplots(1, 2, figsize=(11, 4.4))

axA.plot(vgs, cb, "-", color="#1f77b4", lw=2, label="built-in BSIM4")
axA.plot(vgs[::2], co[::2], "o", color="#1f77b4", ms=5, mfc="none", label="OSDI BSIM4")
axA.set_xlabel("gate voltage  $V_{GS}$  [V]")
axA.set_ylabel("gate capacitance  $C_{gg}$  [fF]")
axA.set_title("A. BSIM4 C-V: OSDI vs built-in")
axA.legend(loc="lower right")
axA.grid(True, alpha=0.3)

fb = [r[0] for r in b4]
axB.loglog(fb, [r[1] for r in b4], "-", color="#1f77b4", lw=2, label="BSIM4 built-in")
axB.loglog(fb[::2], [r[3] for r in b4[::2]], "o", color="#1f77b4", ms=5, mfc="none",
           label="BSIM4 OSDI")
axB.loglog([r[0] for r in hb], [r[1] for r in hb], "-", color="#d62728", lw=2,
           label="HICUML2 OSDI (HBT)")
axB.axhline(1.0, color="#888", lw=1, ls="--")
axB.text(1.2e7, 1.3, "|h21| = 1  (fT)", fontsize=9, color="#555")
axB.set_xlabel("frequency  [Hz]")
axB.set_ylabel("AC current gain  |h21|")
axB.set_ylim(0.3, 200)
axB.set_title("B. Cutoff frequency fT (h21 roll-off)")
axB.legend(loc="lower left", fontsize=8.5)
axB.grid(True, which="both", alpha=0.3)

fig.tight_layout()
out = os.path.join(HERE, "dynmodels_ac.png")
fig.savefig(out, dpi=110)
print("wrote", out)
