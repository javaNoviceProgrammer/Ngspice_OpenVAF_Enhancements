#!/usr/bin/env python3
"""Render an eye diagram PNG from the `eye` command (Enhancement-207).

Drives a pseudo-random bit stream at 2 Gb/s (UI = 0.5 ns) through a
bandwidth-limiting RC channel, so inter-symbol interference partly closes the eye,
runs `eye v(rx) -ui 0.5n`, and plots the folded `eye_wave` vs `eye_t` samples as a
persistence-style 2-D histogram -- the classic eye diagram -- annotated with the
metrics the command reports (eye height/width, RMS jitter).

    python3 make_eye_fig.py     ->  eye_diagram.png
"""
import os
import random
import subprocess
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

UI = 0.5e-9          # 2 Gb/s
NBITS = 800
TR = 12e-12          # driver edge time

# ---- pseudo-random NRZ bit stream as a PWL source -------------------------------
random.seed(7)
bits = [random.randint(0, 1) for _ in range(NBITS)]
pts = [f"0 {bits[0]}"]
for k in range(1, NBITS):
    if bits[k] != bits[k - 1]:
        te = k * UI
        pts.append(f"{te - TR/2:.6e} {bits[k-1]}")
        pts.append(f"{te + TR/2:.6e} {bits[k]}")
pwl = " ".join(pts)

deck = f"""* eye diagram figure: 2 Gb/s PRBS through an RC channel
* channel time constant ~ 0.5 UI (R*C = 250*1p = 250 ps) -> moderate ISI: a partly
* closed but clearly open eye whose 00/01/10/11 sequences trace distinct paths.
Vtx tx 0 PWL({pwl})
Rc tx rx 250
Cc rx 0 1p
.tran 1p {NBITS * 0.5}n
.control
  run
  eye v(rx) -ui 0.5n -tstart 3n
  wrdata {HERE}/_eye.dat eye_wave
  print eye_height
  print eye_width
  print eye_jitter_rms
  print eye_amplitude
  print eye_threshold
.endc
.end
"""
open(os.path.join(HERE, "_eyefig.cir"), "w").write(deck)
r = subprocess.run([NGSPICE, "-b", os.path.join(HERE, "_eyefig.cir")],
                   capture_output=True, text=True, timeout=180)
out = r.stdout + r.stderr

met = {}
for line in out.splitlines():
    if "=" in line and "Reset" not in line and "Circuit" not in line:
        p = line.split("=")
        nm = p[0].strip().split()[-1] if p[0].strip() else ""
        try:
            met[nm] = float(p[1].strip().split()[0])
        except (ValueError, IndexError):
            pass

data = np.loadtxt(os.path.join(HERE, "_eye.dat"))
t = data[:, 0] * 1e9        # ns
v = data[:, 1] * 1e3        # mV

# ---- persistence-style 2-D histogram eye -----------------------------------------
plt.rcParams.update({"font.size": 11})
fig, ax = plt.subplots(figsize=(8.2, 4.8), dpi=140)
fig.patch.set_facecolor("#0d1117")
ax.set_facecolor("#0d1117")

from matplotlib.colors import LogNorm
h = ax.hist2d(t, v, bins=[400, 260], cmap="turbo", norm=LogNorm(),
              range=[[0, 2 * UI * 1e9], [v.min() - 30, v.max() + 30]],
              cmin=1)
cb = fig.colorbar(h[3], ax=ax, pad=0.01)
cb.set_label("sample density (persistence, log)", color="#c9d1d9")
cb.ax.yaxis.set_tick_params(color="#c9d1d9")
plt.setp(plt.getp(cb.ax, "yticklabels"), color="#8b949e")

thr = met.get("eye_threshold", 0.5) * 1e3
ui_ns = UI * 1e9
eh = met.get("eye_height", 0) * 1e3
ew = met.get("eye_width", 0) * 1e9
jr = met.get("eye_jitter_rms", 0) * 1e12
# after folding: crossings land at 0.5 UI and 1.5 UI; the eye CENTRE (sampling
# instant, widest opening) sits at 1.0 UI. Mark the threshold and that centre.
xc = ui_ns                                    # eye centre / sampling instant
ax.axhline(thr, color="#f0f6fc", lw=0.8, ls="--", alpha=0.55)
ax.axvline(xc, color="#f0f6fc", lw=0.9, ls=":", alpha=0.5)
# eye-height double arrow at the eye centre
ax.annotate("", xy=(xc, thr + eh / 2), xytext=(xc, thr - eh / 2),
            arrowprops=dict(arrowstyle="<->", color="#ffffff", lw=1.6))
ax.text(xc + 0.03, thr + eh / 2 + 8, f"eye height\n{eh:.0f} mV",
        color="#ffffff", fontsize=9, va="bottom", ha="left")
# eye-width double arrow along the threshold, centred on the eye centre
ax.annotate("", xy=(xc - ew / 2, thr), xytext=(xc + ew / 2, thr),
            arrowprops=dict(arrowstyle="<->", color="#9be9ff", lw=1.4))
ax.text(xc, thr - 55, f"eye width  {ew*1e3:.0f} ps", color="#9be9ff",
        fontsize=9, ha="center", va="top")

ax.set_xlabel("time within 2 UI  (ns)", color="#c9d1d9")
ax.set_ylabel("v(rx)  (mV)", color="#c9d1d9")
ax.set_title(f"Eye diagram  --  2 Gb/s PRBS through an RC channel  (ngspice `eye`)\n"
             f"UI = {ui_ns:.2f} ns   |   eye height {eh:.0f} mV   |   "
             f"eye width {ew*1e3:.0f} ps ({100*ew/ui_ns:.0f}% UI)   |   "
             f"RMS jitter {jr:.1f} ps",
             color="#f0f6fc", fontsize=10)
ax.tick_params(colors="#8b949e")
for s in ax.spines.values():
    s.set_color("#30363d")

fig.tight_layout()
out_png = os.path.join(HERE, "eye_diagram.png")
fig.savefig(out_png, facecolor=fig.get_facecolor())
print(f"wrote {out_png}")
print(f"  metrics: height {eh:.0f} mV, width {ew*1e3:.0f} ps, jitter {jr:.2f} ps rms")

for f in ("_eyefig.cir", "_eye.dat"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)
