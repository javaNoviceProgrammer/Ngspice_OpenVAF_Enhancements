#!/usr/bin/env python3
"""
plot_mc.py -- renders the Enhancement-66 Monte Carlo distributions as PNGs
(written to plots/): a 500-run seeded alter-loop MC of an OSDI resistor
(gaussian, with the analytic density overlaid) and a 500-run uniform MC
(flat density overlay). Requires matplotlib.
"""
import math
import os
import re
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
PLOTS = os.path.join(HERE, "plots")
os.makedirs(PLOTS, exist_ok=True)

if not os.path.exists(os.path.join(HERE, "mc_blocks.osdi")):
    subprocess.run([OPENVAF, "mc_blocks.va", "-o", "mc_blocks.osdi"],
                   check=True, timeout=300, cwd=HERE)

N = 500
deck = f"""* mc histogram data
.control
pre_osdi mc_blocks.osdi
.endc
V1 a 0 DC 1
N1 a 0 mm
.model mm ires
.control
set numdgt=12
setseed 2026
let n = {N}
let ig = unitvec(n)
let iu = unitvec(n)
let run = 0
dowhile run < n
  let rg = 1k + 33.333*sgauss(0)
  alter @n1[r] = rg
  op
  let ig[run] = i(V1)
  let ru = 1k + 100*sunif(0)
  alter @n1[r] = ru
  op
  let iu[run] = i(V1)
  let run = run + 1
end
print ig
print iu
.endc
.end
"""
open(os.path.join(HERE, "_mch.cir"), "w").write(deck)
r = subprocess.run([NGSPICE, "-b", "_mch.cir"], capture_output=True, text=True,
                   timeout=1800, cwd=HERE)
log = r.stdout + r.stderr

# `print <vec>` emits an indexed table per vector (wrdata is unusable here:
# it pairs vectors with the CURRENT plot's scale, which after the last `op`
# has length 1). Split the log at the second table header.
ig, iu = [], []
current = None
for line in log.splitlines():
    if re.match(r"Index\s+ig", line):
        current = ig
    elif re.match(r"Index\s+iu", line):
        current = iu
    else:
        m = re.match(r"\d+\s+(-?[0-9.eE+-]+)", line)
        if m and current is not None:
            current.append(-float(m.group(1)) * 1e3)   # mA

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))

# gaussian leg: I = 1/R, R ~ N(1k, 33.33)
ax1.hist(ig, bins=30, density=True, alpha=0.65, color="tab:blue",
         label=f"ngspice, {len(ig)} runs")
mu_r, sd_r = 1000.0, 33.333
xs = [min(ig) + k * (max(ig) - min(ig)) / 300 for k in range(301)]
# density of I = 1/R via change of variables: f_I(i) = f_R(1/i) / i^2  (i in mA -> R = 1000/i)
ys = [1000.0 / (x * x) * math.exp(-((1000.0 / x - mu_r) ** 2) / (2 * sd_r ** 2))
      / (sd_r * math.sqrt(2 * math.pi)) for x in xs]
ax1.plot(xs, ys, "-", lw=2.5, color="tab:orange", label="analytic density of 1V/R")
ax1.set_xlabel("current (mA)")
ax1.set_ylabel("probability density")
ax1.set_title("gaussian MC on an OSDI parameter\nR ~ N(1kΩ, 33.3Ω), alter+sgauss, seeded")
ax1.grid(alpha=0.3)
ax1.legend(fontsize=8)

ax2.hist(iu, bins=30, density=True, alpha=0.65, color="tab:blue",
         label=f"ngspice, {len(iu)} runs")
lo, hi = 1000.0 / 1100.0, 1000.0 / 900.0
xs = [lo + k * (hi - lo) / 300 for k in range(301)]
ys = [(1000.0 / (x * x)) / 200.0 for x in xs]   # f_R = 1/200 on [900,1100]
ax2.plot(xs, ys, "-", lw=2.5, color="tab:orange", label="analytic density of 1V/R")
ax2.set_xlabel("current (mA)")
ax2.set_title("uniform MC on an OSDI parameter\nR ~ U[900Ω, 1100Ω]")
ax2.grid(alpha=0.3)
ax2.legend(fontsize=8)

fig.tight_layout()
fig.savefig(os.path.join(PLOTS, "mc_distributions.png"), dpi=130)
print(f"wrote plots/mc_distributions.png ({len(ig)} + {len(iu)} samples)")
