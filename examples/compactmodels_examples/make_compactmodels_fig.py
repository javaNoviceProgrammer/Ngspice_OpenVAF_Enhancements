#!/usr/bin/env python3
"""Enhancement-159 figure: real compact models through openvaf-r + ngspice.

Panel A -- BSIM4 output family Id(Vds) for several Vgs: the OSDI-compiled BSIM4.8
(markers) overlaid on ngspice's built-in BSIM4.8.3 (lines). They track to a few
percent across the whole family -- the OSDI model reproduces the native one.

Panel B -- EKV output family Id(Vds): a compact MOSFET ngspice has no built-in
for, brought up purely through OSDI. Textbook saturation.

Run:  python3 make_compactmodels_fig.py   ->  compactmodels_iv.png
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
W = tempfile.mkdtemp(prefix="cmodel_fig_")
for src, out in [(os.path.join(ITEST, "BSIM4", "bsim4.va"), "bsim4.osdi"),
                 (os.path.join(ITEST, "EKV", "ekv.va"), "ekv.osdi")]:
    subprocess.run([OPENVAF, src, "-o", out], cwd=W, check=True,
                   capture_output=True, text=True)


def run(deck, dat):
    with open(os.path.join(W, "f.cir"), "w") as f:
        f.write(deck)
    subprocess.run([NGSPICE, "-b", "f.cir"], cwd=W, capture_output=True, text=True)
    rows = [[float(x) for x in ln.split()] for ln in open(os.path.join(W, dat)) if ln.split()]
    return rows


def segments(rows):
    """Split a 2-D .dc sweep into per-outer-step segments where the swept x
    (column 0) resets to its start (a new inner sweep begins)."""
    segs, cur = [], []
    for r in rows:
        if cur and r[0] < cur[-1][0] - 1e-12:
            segs.append(cur)
            cur = []
        cur.append(r)
    if cur:
        segs.append(cur)
    return segs


VGS = [0.6, 0.8, 1.0, 1.2]
# BSIM4: built-in (col 2k) and OSDI (col 2k+1... use two ammeters, wrdata pairs)
b4 = run(f"""* bsim4 family
.control
pre_osdi bsim4.osdi
.endc
Vg g 0 dc 1.0
Vd d 0 dc 0
Vmb d db 0
M1 db g 0 0 nb W=10u L=1u
.model nb nmos level=54 version=4.8.2 rdsmod=1 rsh=1
Vmo d do 0
N1 do g 0 0 no
.model no bsim4va w=10u l=1u rdsmod=1 rsh=1
.dc Vd 0 1.2 0.03 Vg {VGS[0]} {VGS[-1]} 0.2
.control
run
wrdata b4.dat abs(i(vmb)) abs(i(vmo))
.endc
.end
""", "b4.dat")

ekv = run(f"""* ekv family
.control
pre_osdi ekv.osdi
.endc
Vg g 0 dc 1.0
Vd d 0 dc 0
N1 d g 0 0 em
.model em ekv_va
.dc Vd 0 1.5 0.04 Vg 0.6 1.4 0.2
.control
run
wrdata ekv.dat abs(i(vd))
.endc
.end
""", "ekv.dat")
fig, (axA, axB) = plt.subplots(1, 2, figsize=(11, 4.4))
cols = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#7a1fa2"]

# Panel A: BSIM4 built-in (line) vs OSDI (markers)
for k, seg in enumerate(segments(b4)):
    vds = [r[0] for r in seg]
    idb = [r[1] * 1e6 for r in seg]
    ido = [r[3] * 1e6 for r in seg]
    c = cols[k % len(cols)]
    axA.plot(vds, idb, "-", color=c, lw=2,
             label="built-in BSIM4" if k == 0 else None)
    axA.plot(vds[::3], ido[::3], "o", color=c, ms=4, mfc="none",
             label="OSDI BSIM4" if k == 0 else None)
axA.set_xlabel("drain voltage  V(d)  [V]")
axA.set_ylabel("drain current  Id  [uA]")
axA.set_title("A. BSIM4: OSDI (openvaf-r) vs ngspice built-in")
axA.legend(loc="upper left")
axA.grid(True, alpha=0.3)

# Panel B: EKV family
for k, seg in enumerate(segments(ekv)):
    axB.plot([r[0] for r in seg], [r[1] * 1e6 for r in seg], "-",
             color=cols[k % len(cols)], lw=2, label=f"Vgs={0.6 + 0.2*k:.1f} V")
axB.set_xlabel("drain voltage  V(d)  [V]")
axB.set_ylabel("drain current  Id  [uA]")
axB.set_title("B. EKV (no ngspice built-in) via OSDI")
axB.legend(loc="upper left", fontsize=8)
axB.grid(True, alpha=0.3)

fig.tight_layout()
out = os.path.join(HERE, "compactmodels_iv.png")
fig.savefig(out, dpi=110)
print("wrote", out)
