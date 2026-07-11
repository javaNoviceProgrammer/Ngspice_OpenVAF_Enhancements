#!/usr/bin/env python3
"""Enhancement-157 figure: device aging (fresh vs aged).

Panel A -- transfer curves Id(Vg) of the demo NMOS `agemos`, fresh and after the
`aging` command has degraded it to 10 / 20 / 40 years of stress at Vg=1.8 V. The
NBTI threshold shift moves the curve right and pulls the current down.

Panel B -- the extracted threshold shift dVth vs stress lifetime (log-log),
showing the sublinear  dVth ~ t^0.25  NBTI power law the model implements.

Run:  python3 make_aging_fig.py   ->  aging_iv.png
"""
import os
import re
import subprocess
import sys
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

W = tempfile.mkdtemp(prefix="aging_fig_")
subprocess.run([OPENVAF, os.path.join(HERE, "agemos.va"), "-o", "agemos.osdi"],
               cwd=W, check=True, capture_output=True, text=True)

MODEL = ".model amos agemos vth0=0.5 kp=100u w=2u l=0.5u\n"


def run(deck):
    with open(os.path.join(W, "_fig.cir"), "w") as f:
        f.write(deck)
    return subprocess.run([NGSPICE, "-b", "_fig.cir"], cwd=W,
                          capture_output=True, text=True).stdout


def transfer(t_age):
    """Id(Vg) sweep after aging the device to t_age seconds (t_age=0 => fresh).

    The drain current is read from the drain-source branch i(vd) -- recorded at
    every sweep point -- rather than an operating-point variable (opvars are not
    swept unless explicitly saved)."""
    age_cmd = "" if t_age <= 0 else f"aging {t_age:g}\n"
    run(f"""* aging transfer curve t={t_age}
.control
pre_osdi agemos.osdi
.endc
Vd d 0 dc 1.0
Vg g 0 dc 1.8
N1 d g 0 amos
{MODEL}.control
{age_cmd}dc Vg 0 1.8 0.02
wrdata _tc.dat i(vd)
.endc
.end
""")
    vg, idv = [], []
    for ln in open(os.path.join(W, "_tc.dat")):
        p = ln.split()
        if len(p) >= 2:
            vg.append(float(p[0]))
            idv.append(abs(float(p[1])))       # |drain current|
    return vg, idv


def vth_after(t_age):
    log = run(f"""* aging vth t={t_age}
.control
pre_osdi agemos.osdi
.endc
Vd d 0 dc 1.0
Vg g 0 dc 1.8
N1 d g 0 amos
{MODEL}.control
aging {t_age:g}
op
set numdgt=10
print @n1[vtheff]
.endc
.end
""")
    m = re.search(r"@n1\[vtheff\]\s*=\s*([0-9.eE+-]+)", log)
    return float(m.group(1)) if m else float("nan")


YEAR = 3.15576e7
fig, (axA, axB) = plt.subplots(1, 2, figsize=(11, 4.3))

# --- Panel A: transfer curves fresh vs aged ---
for t, lab, c in [(0, "fresh", "#1f77b4"),
                  (10 * YEAR, "10 yr", "#ff7f0e"),
                  (20 * YEAR, "20 yr", "#d62728"),
                  (40 * YEAR, "40 yr", "#7a1fa2")]:
    vg, idv = transfer(t)
    axA.plot(vg, [x * 1e6 for x in idv], label=lab, color=c, lw=2)
axA.set_xlabel("gate voltage  V(g)  [V]")
axA.set_ylabel("drain current  Id  [uA]")
axA.set_title("A. Transfer curve: NBTI aging at Vg = 1.8 V")
axA.legend(title="stress time")
axA.grid(True, alpha=0.3)

# --- Panel B: dVth vs stress time (power law) ---
years = [0.1, 0.3, 1, 3, 10, 30, 100]
ts = [y * YEAR for y in years]
dvth = [vth_after(t) - 0.5 for t in ts]
axB.loglog(years, [d * 1e3 for d in dvth], "o-", color="#d62728", lw=2, ms=6,
           label="simulated")
# reference slope-0.25 guide through the 10-year point
i10 = years.index(10)
guide = [dvth[i10] * (y / 10) ** 0.25 * 1e3 for y in years]
axB.loglog(years, guide, "k--", lw=1, alpha=0.6, label=r"$\propto t^{0.25}$")
axB.set_xlabel("stress time  [years]")
axB.set_ylabel(r"threshold shift  $\Delta V_{th}$  [mV]")
axB.set_title("B. NBTI power law  " + r"$\Delta V_{th}\propto t^{0.25}$")
axB.legend()
axB.grid(True, which="both", alpha=0.3)

fig.tight_layout()
out = os.path.join(HERE, "aging_iv.png")
fig.savefig(out, dpi=110)
print("wrote", out)
