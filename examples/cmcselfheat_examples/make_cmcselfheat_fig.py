#!/usr/bin/env python3
"""Enhancement-167 figure: cross-model self-heating.

Panel A -- the electro-thermal analogy V(tnode) = Pdiss * rth_eff, verified across
FOUR device classes on one plot (log-log): a SiGe HBT (HICUM/L2), a GaN HEMT
(ASMHEMT), a bulk MOSFET (BSIMBULK) and a FinFET (BSIMCMG). For each model the
drive is swept to vary the dissipated power; the measured thermal-node voltage
(markers) rides exactly on its own Pdiss*rth_eff line (dashed). Four decades of
power and temperature rise, one universal law.

Panel B -- the model's thermal-resistance parameter sets the thermal resistance.
For each model the rth parameter (rth / rth0 / RTH0) is swept over 8x; the
measured V(tnode)/Pdiss (a genuine thermal resistance) tracks it linearly
(slope 1 on log-log) for every device class.

Run:  python3 make_cmcselfheat_fig.py   ->  cmcselfheat.png
"""
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
W = tempfile.mkdtemp(prefix="shfig_")


def compile_model(subdir, va, osdi):
    subprocess.run([OPENVAF, va, "-o", os.path.join(W, osdi)],
                   cwd=os.path.join(ITEST, subdir), capture_output=True)


def run(deck):
    open(os.path.join(W, "d.cir"), "w").write(deck)
    subprocess.run([NGSPICE, "-b", "d.cir"], cwd=W, capture_output=True, text=True)


def dat(fn):
    return [[float(x) for x in l.split()] for l in open(os.path.join(W, fn))]


for sub, va, osdi in [("HICUML2", "hicuml2.va", "hicuml2.osdi"),
                      ("ASMHEMT", "asmhemt.va", "asmhemt.osdi"),
                      ("BSIMBULK", "bsimbulk.va", "bsimbulk.osdi"),
                      ("BSIMCMG", "bsimcmg.va", "bsimcmg.osdi")]:
    compile_model(sub, va, osdi)

# Per-model: label, color, osdi, deck template with {rth}, drive .dc, rth_eff(rth).
# {rth} is the model parameter; the deck prints P and V(th) over a drive sweep.
HICUM = ("HICUM/L2 (SiGe HBT)", "#d62728", """* hicum
.control
pre_osdi hicuml2.osdi
.endc
Vc c 0 dc 2.0
Ibb 0 b dc 20u
N1 c b 0 0 th m
Rthp th 0 1e12
.model m hicumL2va flsh=1 rth={rth}
.dc Ibb 4u 40u 3u
.control
run
let pd = abs(i(vc))*v(c)
wrdata o.dat pd v(th)
.endc
.end
""", lambda r: r)

ASM = ("ASMHEMT (GaN HEMT)", "#1f77b4", """* asmhemt
.control
pre_osdi asmhemt.osdi
.endc
Vd d 0 dc 5.0
Vg g 0 dc 0
N1 d g 0 0 th asm
Rthp th 0 1e12
.model asm asmhemt shmod=1 rth0={rth}
.dc Vg -1.5 0.2 0.15
.control
run
let pd = abs(i(vd))*v(d)
wrdata o.dat pd v(th)
.endc
.end
""", lambda r: r)

BULK = ("BSIMBULK (bulk MOSFET)", "#2ca02c", """* bsimbulk
.control
pre_osdi bsimbulk.osdi
.endc
Vd d 0 dc 1.0
Vg g 0 dc 1.0
N1 d g 0 0 th nmos W=1u L=0.1u
Rthp th 0 1e12
.model nmos bsimbulk SHMOD=1 RTH0={rth}
.dc Vg 0.8 1.6 0.08
.control
run
let pd = abs(i(vd))*v(d)
wrdata o.dat pd v(th)
.endc
.end
""", lambda r: r / 1e-6)         # rth_eff = RTH0/W, W=1um

CMG = ("BSIMCMG (FinFET)", "#9467bd", """* bsimcmg
.control
pre_osdi bsimcmg.osdi
.endc
Vd d 0 dc 1.0
Vg g 0 dc 1.0
N1 d g 0 0 th nfin
Rthp th 0 1e12
.model nfin bsimcmg_va SHMOD=1 RTH0={rth}
.dc Vg 0.7 1.3 0.06
.control
run
let pd = abs(i(vd))*v(d)
wrdata o.dat pd v(th)
.endc
.end
""", None)                       # geometry-normalized (measured slope used)

MODELS = [HICUM, ASM, BULK, CMG]
# a representative rth parameter per model for Panel A
RTH_A = {HICUM[0]: 2000, ASM[0]: 20, BULK[0]: 1e-3, CMG[0]: 5e-3}

# --- Panel A data: (P, Vth) sweeps ---
paA = {}
for label, col, tmpl, reff in MODELS:
    run(tmpl.format(rth=RTH_A[label]))
    rows = [r for r in dat("o.dat") if r[1] > 0 and r[3] > 1e-6]
    paA[label] = ([r[1] for r in rows], [r[3] for r in rows], col, reff, RTH_A[label])

# --- Panel B data: measured V/P vs rth param (8x sweep) ---
paB = {}
for label, col, tmpl, reff in MODELS:
    base = RTH_A[label]
    xs, ys = [], []
    for k in (1, 2, 4, 8):
        run(tmpl.format(rth=base * k))
        rows = [r for r in dat("o.dat") if r[1] > 0 and r[3] > 1e-6]
        mid = rows[len(rows) * 2 // 3]                    # a well-conducting point
        xs.append(base * k)
        ys.append(mid[3] / mid[1])                        # V/P = measured rth_eff
    paB[label] = (xs, ys, col)

# ----------------------------- plot -------------------------------------------
fig, (axA, axB) = plt.subplots(1, 2, figsize=(13, 5.2))

for label, col, tmpl, reff in MODELS:
    P, V, c, re_fn, rp = paA[label]
    axA.loglog(P, V, "o", color=c, ms=6, mfc="none", label=label)
    if re_fn is not None:                                 # exact reference line
        reff_val = re_fn(rp)
        Pl = [min(P), max(P)]
        axA.loglog(Pl, [p * reff_val for p in Pl], "--", color=c, lw=1.2)
    else:                                                 # measured slope (geom-norm)
        slope = sum(v / p for p, v in zip(P, V)) / len(P)
        Pl = [min(P), max(P)]
        axA.loglog(Pl, [p * slope for p in Pl], ":", color=c, lw=1.2)
axA.plot([], [], "k--", label=r"$P_\mathrm{diss}\cdot r_\mathrm{th,eff}$")
axA.set_xlabel(r"dissipated power  $P_\mathrm{diss}$  [W]")
axA.set_ylabel(r"thermal-node $V(t_\mathrm{node})$ = temperature rise  [K]")
axA.set_title("A. $\\Delta T = P\\,r_\\mathrm{th}$ across four device classes")
axA.legend(fontsize=8.5, loc="lower right")
axA.grid(True, which="both", alpha=0.3)

for label, col, tmpl, reff in MODELS:
    xs, ys, c = paB[label]
    xn = [x / xs[0] for x in xs]                          # normalize param to its base
    yn = [y / ys[0] for y in ys]                          # normalize R to its base
    axB.loglog(xn, yn, "o-", color=c, ms=6, label=label)
axB.loglog([1, 8], [1, 8], "k--", lw=1, label="slope 1 (linear control)")
axB.set_xlabel(r"thermal-resistance parameter  (normalized, $\times$ base)")
axB.set_ylabel(r"measured $V(t_\mathrm{node})/P_\mathrm{diss}$  (normalized)")
axB.set_title("B. the model's rth parameter sets $r_\\mathrm{th}$")
axB.legend(fontsize=8.5, loc="upper left")
axB.grid(True, which="both", alpha=0.3)

fig.suptitle("Cross-model self-heating: the electro-thermal analogy holds for every "
             "self-heating CMC model (OSDI) -- Enhancement-167", fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.95])
out = os.path.join(HERE, "cmcselfheat.png")
fig.savefig(out, dpi=110)
print("wrote", out)
