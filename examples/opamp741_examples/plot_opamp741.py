#!/usr/bin/env python3
"""Render the uA741 characterization figure from results/ (run
run_opamp741.py first)."""
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results")
os.makedirs(os.path.join(HERE, "plots"), exist_ok=True)

fol = np.loadtxt(os.path.join(R, "dc_follower.txt"))
ol = np.loadtxt(os.path.join(R, "dc_openloop.txt"))
ac = np.loadtxt(os.path.join(R, "ac_openloop.txt"))
st = np.loadtxt(os.path.join(R, "tran_step.txt"))
sl = np.loadtxt(os.path.join(R, "tran_slew.txt"))

fig, axes = plt.subplots(2, 2, figsize=(12.5, 8.5))
(axd, axa), (axs, axl) = axes

# DC
axd.plot(fol[:, 0], fol[:, 1], label="follower  v(out)")
axd.plot(fol[:, 0], fol[:, 0], "--", alpha=0.4, label="ideal")
axi = axd.inset_axes([0.55, 0.12, 0.4, 0.35])
axi.plot(ol[:, 0] * 1e3, ol[:, 1])
axi.set_xlabel("$V_{id}$ [mV]", fontsize=8)
axi.set_title("open-loop VTC", fontsize=8)
axi.tick_params(labelsize=7)
axd.set_xlabel("input [V]")
axd.set_ylabel("output [V]")
axd.set_title("DC: unity follower + open-loop transfer")
axd.legend(loc="upper left")
axd.grid(alpha=0.3)

# AC Bode
axa.semilogx(ac[:, 0], ac[:, 1], "C0", label="|A| [dB]")
axa.set_xlabel("frequency [Hz]")
axa.set_ylabel("open-loop gain [dB]", color="C0")
axa.axhline(0, color="k", lw=0.6, alpha=0.5)
ax2 = axa.twinx()
ph = np.degrees(np.unwrap(ac[:, 2]))
ph -= ph[np.argmax(ac[:, 1])]          # reference the flat band to 0 lag
ax2.semilogx(ac[:, 0], ph, "C1", label="phase lag [deg]")
ax2.set_ylabel("phase (rel. flat band) [deg]", color="C1")
axa.set_title("AC: open-loop gain / phase (L-C biased)")
axa.grid(alpha=0.3, which="both")

# small step
axs.plot(st[:, 0] * 1e6, st[:, 1] * 1e3, "--", alpha=0.5, label="in")
axs.plot(st[:, 0] * 1e6, st[:, 2] * 1e3, label="out")
axs.set_xlabel("t [µs]")
axs.set_ylabel("[mV]")
axs.set_title("Transient: follower 100 mV step")
axs.legend()
axs.grid(alpha=0.3)
axs.set_xlim(0, 12)

# slew
axl.plot(sl[:, 0] * 1e6, sl[:, 1], "--", alpha=0.5, label="in")
axl.plot(sl[:, 0] * 1e6, sl[:, 2], label="out")
axl.set_xlabel("t [µs]")
axl.set_ylabel("[V]")
axl.set_title("Transient: ±5 V square — slew limiting")
axl.legend()
axl.grid(alpha=0.3)

fig.suptitle("Transistor-level µA741 from a Verilog-A BJT (openvaf-r + ngspice)",
             fontsize=13)
fig.tight_layout()
fig.savefig(os.path.join(HERE, "plots", "opamp741.png"), dpi=110)
print("wrote plots/opamp741.png")
