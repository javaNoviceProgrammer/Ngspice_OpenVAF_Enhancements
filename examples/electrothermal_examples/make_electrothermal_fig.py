#!/usr/bin/env python3
"""Enhancement-166 figure: electro-thermal / self-heating of a compact model.

Panel A -- STATIC analogy. A current-biased HICUM/L2 stage, its thermal node
exposed as an extra terminal. The measured thermal-node "voltage" V(tnode)
(markers) is the temperature rise; it lands exactly on the line Pdiss*rth
(dashed) across a decade of dissipated power, for two thermal resistances. The
electro-thermal analogy voltage<->temperature, current<->power is exact.

Panel B -- FEEDBACK / RUNAWAY. A Gummel plot Ic(Vbe), log-y. Isothermal
(flsh=0, line) is the usual exponential; with self-heating on (flsh=1, rth=1500,
markers) each rise in current heats the junction, which raises the current
further -- positive feedback that peels the curve up and runs it away at high
bias. This is why real bias networks use current sources or emitter degeneration.

Panel C -- DYNAMIC. After a collector-voltage (power) step the thermal node
rises as a single pole to its new steady value, with time constant tau = rth*cth.
Two thermal capacitances give two time constants (2 ms and 4 ms); the 63.2%
markers sit one tau after the step on each curve.

Run:  python3 make_electrothermal_fig.py   ->  electrothermal.png
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
W = tempfile.mkdtemp(prefix="etfig_")
subprocess.run([OPENVAF, "hicuml2.va", "-o", os.path.join(W, "hicuml2.osdi")],
               cwd=os.path.join(ITEST, "HICUML2"), capture_output=True)


def run(deck):
    open(os.path.join(W, "d.cir"), "w").write(deck)
    subprocess.run([NGSPICE, "-b", "d.cir"], cwd=W, capture_output=True, text=True)


def dat(fn):
    return [[float(x) for x in l.split()] for l in open(os.path.join(W, fn))]


# --- Panel A: V(tnode) vs power, two rth ---
paA = {}
for rth in (1500, 3000):
    run(f"""* Vtnode vs power
.control
pre_osdi hicuml2.osdi
.endc
Vc c 0 dc 2.0
Ibb 0 b dc 5u
N1 c b 0 0 th m
.model m hicumL2va flsh=1 rth={rth}
.dc Ibb 2u 44u 2u
.control
run
let pdiss = abs(i(vc))*2.0
wrdata pa{rth}.dat pdiss v(th)
.endc
.end
""")
    rows = dat(f"pa{rth}.dat")
    paA[rth] = ([r[1] for r in rows], [r[3] for r in rows])   # P, V(th)

# --- Panel B: Gummel Ic(Vbe), isothermal vs self-heated ---
def gummel(mp, tn):
    run(f"""* gummel
.control
pre_osdi hicuml2.osdi
.endc
Vc c 0 dc 2.0
Vb b 0 dc 0.6
N1 c b 0 0 {tn} m
.model m hicumL2va {mp}
.dc Vb 0.45 0.84 0.01
.control
run
wrdata gm.dat abs(i(vc))
.endc
.end
""")
    rows = dat("gm.dat")
    return [r[0] for r in rows], [r[1] for r in rows]

vb_iso, ic_iso = gummel("flsh=0", "0")
vb_sh, ic_sh = gummel("flsh=1 rth=1500", "th")

# --- Panel C: thermal transient, two cth ---
paC = {}
for cth, tau in ((1e-6, 2e-3), (2e-6, 4e-3)):
    run(f"""* thermal transient
.control
pre_osdi hicuml2.osdi
.endc
Vc c 0 dc 2.0 pwl(0 2.0 0.9999m 2.0 1.0m 3.5 40m 3.5)
Ibb 0 b dc 20u
N1 c b 0 0 th m
.model m hicumL2va flsh=1 rth=2000 cth={cth}
.tran 40u 30m
.control
run
wrdata tt{cth}.dat v(th)
.endc
.end
""")
    rows = dat(f"tt{cth}.dat")
    paC[cth] = ([r[0] for r in rows], [r[1] for r in rows], tau)

# ----------------------------- plot -------------------------------------------
fig, (axA, axB, axC) = plt.subplots(1, 3, figsize=(15, 4.5))
C1, C2 = "#1f77b4", "#d62728"

# A
for rth, col in ((1500, C1), (3000, C2)):
    P, V = paA[rth]
    axA.plot([p * 1e3 for p in P], V, "o", color=col, ms=6, mfc="none",
             label=f"rth={rth} K/W (measured)")
    axA.plot([p * 1e3 for p in P], [p * rth for p in P], "--", color=col, lw=1.3)
axA.plot([], [], "k--", label=r"$P_\mathrm{diss}\cdot r_\mathrm{th}$ (exact)")
axA.set_xlabel("dissipated power  $P_\\mathrm{diss}$  [mW]")
axA.set_ylabel(r"thermal-node $V(t_\mathrm{node})$ = temperature rise  [K]")
axA.set_title("A. static analogy:  $\\Delta T = P\\,r_\\mathrm{th}$")
axA.legend(fontsize=8.5)
axA.grid(True, alpha=0.3)

# B
axB.semilogy(vb_iso, ic_iso, "-", color=C1, lw=2, label="isothermal (flsh=0)")
axB.semilogy(vb_sh[::2], ic_sh[::2], "o", color=C2, ms=6, mfc="none",
             label="self-heated (flsh=1, rth=1500)")
axB.set_xlabel(r"base-emitter voltage  $V_\mathrm{BE}$  [V]")
axB.set_ylabel(r"collector current  $I_C$  [A]")
axB.set_title("B. feedback: self-heating runaway")
axB.legend(fontsize=8.5, loc="upper left")
axB.grid(True, which="both", alpha=0.3)
axB.annotate("thermal\nrunaway", xy=(0.83, ic_sh[-2]), xytext=(0.70, 1e1),
             fontsize=9, color=C2, ha="center",
             arrowprops=dict(arrowstyle="->", color=C2))

# C
for cth, col in ((1e-6, C1), (2e-6, C2)):
    t, v, tau = paC[cth]
    axC.plot([tt * 1e3 for tt in t], v, "-", color=col, lw=2,
             label=f"cth={cth*1e6:.0f} uF/K,  tau=rth*cth={tau*1e3:.0f} ms")
    at = lambda tt: v[min(range(len(t)), key=lambda k: abs(t[k] - tt))]
    v0, vf = at(0.95e-3), at(28e-3)
    axC.plot([(1e-3 + tau) * 1e3], [v0 + 0.632 * (vf - v0)], "s", color=col, ms=8)
axC.plot([], [], "ks", ms=8, label=r"63.2% of rise, one $\tau$ after step")
axC.axvline(1.0, color="#888", ls=":", lw=1)
axC.set_xlabel("time  [ms]")
axC.set_ylabel(r"thermal-node $V(t_\mathrm{node})$  [K]")
axC.set_title("C. dynamic: thermal transient  $\\tau = r_\\mathrm{th} c_\\mathrm{th}$")
axC.legend(fontsize=8.5, loc="lower right")
axC.grid(True, alpha=0.3)

fig.suptitle("Electro-thermal self-heating of a production compact model "
             "(HICUM/L2, OSDI) -- Enhancement-166", fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.96])
out = os.path.join(HERE, "electrothermal.png")
fig.savefig(out, dpi=110)
print("wrote", out)
