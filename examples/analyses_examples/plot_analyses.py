#!/usr/bin/env python3
"""
plot_analyses.py -- renders the Enhancement-62 sweep results as PNG plots
(written to plots/). Runs ngspice on the tutorial decks in this folder:

  param_sweep.png  : .dc @n1[r] instance-parameter sweep vs analytic 1/R
  nested_sweep.png : @n1[r] sweep nested inside a V1 sweep (curve family)
  temp_sweep.png   : .dc temp with a $temperature-dependent OSDI resistor
  ac_lowpass.png   : OSDI RC lowpass |H| and phase; the .pz pole and the
                     .sens AC operating point marked at f = 1/(2*pi*RC)

Requires matplotlib.
"""
import math
import os
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


def ensure_osdi(name):
    if not os.path.exists(os.path.join(HERE, name + ".osdi")):
        subprocess.run([OPENVAF, name + ".va", "-o", name + ".osdi"],
                       check=True, timeout=300, cwd=HERE)


def run_deck(deck):
    subprocess.run([NGSPICE, "-b", deck], capture_output=True, text=True,
                   timeout=300, cwd=HERE)


def read_wrdata(name, ycols=1):
    """wrdata format: x y1 [x y2 ...] per line."""
    rows = []
    with open(os.path.join(HERE, name)) as fh:
        for line in fh:
            p = line.split()
            if len(p) >= 2 * ycols:
                rows.append((float(p[0]), *[float(p[2*k+1]) for k in range(ycols)]))
    return rows


ensure_osdi("analyses_blocks")
ensure_osdi("analyses_dio")

# ---------------------------------------------------------------- param sweep
run_deck("param_sweep.cir")
rows = read_wrdata("_param_sweep.txt")
r = [x for x, _ in rows]
i_meas = [-y * 1e3 for _, y in rows]           # mA, source convention flipped
i_ref = [1.0 / x * 1e3 for x in r]             # 1V / R in mA

fig, ax = plt.subplots(figsize=(7, 4.5))
ax.plot(r, i_ref, "-", lw=4, alpha=0.35, color="tab:orange", label="analytic  I = 1V / r")
ax.plot(r, i_meas, ".", ms=5, color="tab:blue", label="ngspice  .dc @n1[r]")
ax.set_xlabel("swept instance parameter  @n1[r]  (Ω)")
ax.set_ylabel("current through the device (mA)")
ax.set_title(".dc @inst[param] — sweeping an OSDI instance parameter (E-62)")
ax.grid(alpha=0.3)
ax.legend()
fig.tight_layout()
fig.savefig(os.path.join(PLOTS, "param_sweep.png"), dpi=130)
plt.close(fig)
print("wrote plots/param_sweep.png")

# --------------------------------------------------------------- nested sweep
run_deck("nested_sweep.cir")
rows = read_wrdata("_nested_sweep.txt")
# rows come out flattened: inner @n1[r] 500..4000 for V1 = 1, 2, 3
npts = sum(1 for k in range(len(rows)) if k == 0 or rows[k][0] > rows[k-1][0]
           and (k == 0 or rows[k-1][0] != 4000.0)) # not robust; split on x reset instead
curves = []
cur = []
prev_x = None
for x, y in rows:
    if prev_x is not None and x < prev_x:
        curves.append(cur)
        cur = []
    cur.append((x, y))
    prev_x = x
curves.append(cur)

fig, ax = plt.subplots(figsize=(7, 4.5))
colors = ["tab:blue", "tab:orange", "tab:green"]
for k, curve in enumerate(curves):
    xs = [x for x, _ in curve]
    ys = [-y * 1e3 for _, y in curve]
    v = k + 1
    ax.plot(xs, [v / x * 1e3 for x in xs], "-", lw=4, alpha=0.3, color=colors[k % 3])
    ax.plot(xs, ys, ".", ms=4, color=colors[k % 3], label=f"V1 = {v} V")
ax.set_xlabel("inner sweep  @n1[r]  (Ω)")
ax.set_ylabel("current (mA)")
ax.set_title("nested .dc — @n1[r] inside a V1 sweep (dots: ngspice, bands: analytic)")
ax.grid(alpha=0.3)
ax.legend(title="outer sweep")
fig.tight_layout()
fig.savefig(os.path.join(PLOTS, "nested_sweep.png"), dpi=130)
plt.close(fig)
print(f"wrote plots/nested_sweep.png ({len(curves)} curves)")

# ----------------------------------------------------------------- temp sweep
run_deck("temp_sweep.cir")
rows = read_wrdata("_temp_sweep.txt")
tc = [x for x, _ in rows]
i_meas = [-y * 1e3 for _, y in rows]
i_ref = [1e3 / (1e3 * (1.0 + 0.01 * ((x + 273.15) - 300.0))) for x in tc]

fig, ax = plt.subplots(figsize=(7, 4.5))
ax.plot(tc, i_ref, "-", lw=4, alpha=0.35, color="tab:orange",
        label="analytic  I = 1V / R(T),  R(T) = r0·(1 + tc·(T−300K))")
ax.plot(tc, i_meas, ".", ms=5, color="tab:blue", label="ngspice  .dc temp")
ax.set_xlabel("circuit temperature (°C)")
ax.set_ylabel("current (mA)")
ax.set_title(".dc temp — $temperature-dependent OSDI resistor")
ax.grid(alpha=0.3)
ax.legend()
fig.tight_layout()
fig.savefig(os.path.join(PLOTS, "temp_sweep.png"), dpi=130)
plt.close(fig)
print("wrote plots/temp_sweep.png")

# ----------------------------------------------------------------- ac lowpass
with open(os.path.join(HERE, "_ac_lowpass.cir"), "w") as fh:
    fh.write("""* ac sweep of the OSDI RC lowpass (for ac_lowpass.png)
.control
pre_osdi analyses_blocks.osdi
.endc
V1 in 0 DC 0 AC 1
N1 in out mmr
.model mmr ores r=1k
N2 out 0 mmc
.model mmc ocap cap=1n
.ac dec 40 1k 100meg
.control
run
wrdata _ac_lowpass.txt vm(out) vp(out)
.endc
.end
""")
run_deck("_ac_lowpass.cir")
rows = read_wrdata("_ac_lowpass.txt", ycols=2)
f = [x for x, _, _ in rows]
mag_db = [20 * math.log10(max(m, 1e-30)) for _, m, _ in rows]
ph_deg = [p * 180 / math.pi for _, _, p in rows]
fpole = 1.0 / (2 * math.pi * 1e3 * 1e-9)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 6), sharex=True)
ax1.semilogx(f, mag_db, color="tab:blue")
ax1.axvline(fpole, color="tab:red", ls="--", alpha=0.7)
ax1.plot([fpole], [20 * math.log10(1 / math.sqrt(2))], "o", color="tab:red",
         label=".pz pole −1/(RC) = −1e6 rad/s → f = 159.2 kHz (−3 dB)")
ax1.set_ylabel("|V(out)/V(in)|  (dB)")
ax1.set_title("OSDI RC lowpass — ties .ac, .pz, and .sens ac together")
ax1.grid(alpha=0.3, which="both")
ax1.legend(fontsize=8)
ax2.semilogx(f, ph_deg, color="tab:blue")
ax2.axvline(fpole, color="tab:red", ls="--", alpha=0.7)
ax2.plot([fpole], [-45.0], "o", color="tab:red",
         label=".sens ac point: H = 1/(1+j) = 0.5−0.5j (−45°)")
ax2.set_xlabel("frequency (Hz)")
ax2.set_ylabel("phase (°)")
ax2.grid(alpha=0.3, which="both")
ax2.legend(fontsize=8)
fig.tight_layout()
fig.savefig(os.path.join(PLOTS, "ac_lowpass.png"), dpi=130)
plt.close(fig)
print("wrote plots/ac_lowpass.png")

print("done")
