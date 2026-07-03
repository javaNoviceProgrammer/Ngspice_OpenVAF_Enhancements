#!/usr/bin/env python3
"""Plot DC/AC/transient results for the indirect branch assignment (ideal
op-amp unity-gain buffer) examples. wrdata writes "x1 y1 x2 y2 ..." columns,
one (x, y) pair per plotted vector, all sharing the same x sweep here."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# DC: v(pin), v(out)
d = np.loadtxt("dc.txt")
plt.figure(figsize=(6, 4.5))
plt.plot(d[:, 0], d[:, 1], "o-", label="V(pin)")
plt.plot(d[:, 2], d[:, 3], "x--", label="V(out)")
plt.xlabel("V(pin) sweep [V]")
plt.ylabel("Voltage [V]")
plt.title("Ideal op-amp unity-gain buffer - DC sweep")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.savefig("dc.png", dpi=150)
plt.close()

# AC: vdb(out), vp(out)
a = np.loadtxt("ac.txt")
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(6, 6), sharex=True)
ax1.semilogx(a[:, 0], a[:, 1], marker="o", ms=3)
ax1.set_ylabel("Gain [dB]")
ax1.set_ylim(-1, 1)
ax1.set_title("Ideal op-amp unity-gain buffer - AC response")
ax1.grid(True, which="both")
ax2.semilogx(a[:, 2], a[:, 3], marker="o", ms=3, color="tab:orange")
ax2.set_ylabel("Phase [deg]")
ax2.set_ylim(-1, 1)
ax2.set_xlabel("Frequency [Hz]")
ax2.grid(True, which="both")
plt.tight_layout()
plt.savefig("ac.png", dpi=150)
plt.close()

# Transient: v(pin), v(out)
t = np.loadtxt("tran.txt")
plt.figure(figsize=(6, 4.5))
plt.plot(t[:, 0] * 1e6, t[:, 1], label="V(pin)")
plt.plot(t[:, 2] * 1e6, t[:, 3], "--", label="V(out)")
plt.xlabel("Time [us]")
plt.ylabel("Voltage [V]")
plt.title("Ideal op-amp unity-gain buffer - Transient response")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.savefig("tran.png", dpi=150)
plt.close()

print("wrote dc.png, ac.png, tran.png")
