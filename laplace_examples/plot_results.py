#!/usr/bin/env python3
"""Plot DC/AC/transient results for the laplace_lpf example
(H(s) = 1/(1+tau*s), tau=1e-6s -> corner frequency f_p = 1/(2*pi*tau)).

wrdata writes "x1 y1 x2 y2 ..." columns, one (x, y) pair per plotted
vector. Phase from this ngspice build's vp() is in radians, converted to
degrees below for a conventional Bode plot.
"""
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

matplotlib.rcParams.update(
    {
        "font.size": 8,
        "axes.titlesize": 8,
        "axes.labelsize": 8,
        "legend.fontsize": 7,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
    }
)

TAU = 1e-6
F_POLE = 1.0 / (2 * np.pi * TAU)
FIGSIZE = (3.2, 2.6)
DPI = 130

# --- DC: v(in), v(out) ------------------------------------------------
d = np.loadtxt("dc.txt")
plt.figure(figsize=FIGSIZE)
plt.plot(d[:, 0], d[:, 1], "k--", lw=1, label="V(in)")
plt.plot(d[:, 2], d[:, 3], "o-", ms=3, color="tab:blue", label="V(out)")
plt.xlabel("V(in) sweep [V]")
plt.ylabel("Voltage [V]")
plt.title("laplace_lpf - DC sweep")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.savefig("dc.png", dpi=DPI)
plt.close()

# --- AC: vdb(out), vp(out) (phase in rad -> deg) -----------------------
a = np.loadtxt("ac.txt")
freq = a[:, 0]
gain_db = a[:, 1]
phase_deg = np.degrees(a[:, 3])

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=FIGSIZE, sharex=True)
ax1.semilogx(freq, gain_db, color="tab:blue", label="V(out)")
ax1.axvline(F_POLE, color="gray", ls=":", lw=1)
ax1.axhline(-3.0, color="gray", ls=":", lw=1)
ax1.set_ylabel("Gain [dB]")
ax1.set_title("laplace_lpf - AC response")
ax1.grid(True, which="both")

ax2.semilogx(freq, phase_deg, color="tab:blue")
ax2.axvline(F_POLE, color="gray", ls=":", lw=1)
ax2.axhline(-45.0, color="gray", ls=":", lw=1)
ax2.set_ylabel("Phase [deg]")
ax2.set_xlabel("Frequency [Hz]")
ax2.grid(True, which="both")
plt.tight_layout()
plt.savefig("ac.png", dpi=DPI)
plt.close()

# --- Transient: v(in), v(out) step response -----------------------------
t = np.loadtxt("tran.txt")
time_us = t[:, 0] * 1e6
plt.figure(figsize=FIGSIZE)
plt.plot(time_us, t[:, 1], "k--", lw=1, label="V(in)")
plt.plot(time_us, t[:, 3], color="tab:blue", label="V(out)")
plt.axvline(TAU * 1e6, color="gray", ls=":", lw=1)
plt.axhline(1 - np.exp(-1), color="gray", ls=":", lw=1)
plt.xlabel("Time [us]")
plt.ylabel("Voltage [V]")
plt.title("laplace_lpf - Transient response")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.savefig("tran.png", dpi=DPI)
plt.close()

print("wrote dc.png, ac.png, tran.png")
