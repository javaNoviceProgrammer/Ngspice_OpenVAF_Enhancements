#!/usr/bin/env python3
"""Plot DC/AC/transient results for the bus_buffer (vectored/bus port)
example. wrdata writes "x1 y1 x2 y2 ..." columns, one (x, y) pair per
plotted vector, all sharing the same x sweep here."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

TAPS = ["out[0]", "out[1]", "out[2]", "out[3]"]
COLORS = ["tab:blue", "tab:orange", "tab:green", "tab:red"]

# DC: v(in), v(out0), v(out1), v(out2), v(out3) -- wrdata emits an (x, y)
# column pair per plotted vector, so tap i's value is column 3 + 2*i.
d = np.loadtxt("dc.txt")
plt.figure(figsize=(6, 4.5))
for i, (label, color) in enumerate(zip(TAPS, COLORS)):
    plt.plot(d[:, 0], d[:, 3 + 2 * i], "o-", ms=3, color=color, label=f"V({label})")
plt.xlabel("V(in) sweep [V]")
plt.ylabel("Voltage [V]")
plt.title("bus_buffer - DC sweep (4-tap bus output)")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.savefig("dc.png", dpi=150)
plt.close()

# AC: vdb(out_i), vp(out_i) for each tap
a = np.loadtxt("ac.txt")
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(6, 6), sharex=True)
for i, (label, color) in enumerate(zip(TAPS, COLORS)):
    freq = a[:, 4 * i]
    gain = a[:, 4 * i + 1]
    phase = a[:, 4 * i + 3]
    ax1.semilogx(freq, gain, marker="o", ms=3, color=color, label=label)
    ax2.semilogx(freq, phase, marker="o", ms=3, color=color, label=label)
ax1.set_ylabel("Gain [dB]")
ax1.set_title("bus_buffer - AC response (4-tap bus output)")
ax1.grid(True, which="both")
ax1.legend()
ax2.set_ylabel("Phase [deg]")
ax2.set_xlabel("Frequency [Hz]")
ax2.set_ylim(-1, 1)
ax2.grid(True, which="both")
plt.tight_layout()
plt.savefig("ac.png", dpi=150)
plt.close()

# Transient: v(in), v(out0), v(out1), v(out2), v(out3)
t = np.loadtxt("tran.txt")
plt.figure(figsize=(6, 4.5))
plt.plot(t[:, 0] * 1e6, t[:, 1], "k--", label="V(in)")
for i, (label, color) in enumerate(zip(TAPS, COLORS)):
    plt.plot(t[:, 2 * (i + 1)] * 1e6, t[:, 2 * (i + 1) + 1], color=color, label=f"V({label})")
plt.xlabel("Time [us]")
plt.ylabel("Voltage [V]")
plt.title("bus_buffer - Transient response (4-tap bus output)")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.savefig("tran.png", dpi=150)
plt.close()

print("wrote dc.png, ac.png, tran.png")
