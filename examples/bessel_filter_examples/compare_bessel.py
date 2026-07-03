#!/usr/bin/env python3
"""Compare the ngspice/OpenVAF laplace_nd Bessel-filter simulation against
the analytical transfer function computed directly by scipy (the same b,a
scipy.signal.bessel(...) coefficients that design_bessel.py wrote into
bessel5.va), for both AC (Bode) and transient (step) response."""
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import signal

from design_bessel import b, a, FC_HZ, N

# --- AC: ngspice vdb(out), vp(out) vs. scipy.signal.freqs -------------------
ac = np.loadtxt("ac.txt")
freq = ac[:, 0]
gain_db_sim = ac[:, 1]
phase_deg_sim = np.degrees(ac[:, 3])  # ngspice vp() is in radians on this build

w = 2 * np.pi * freq
_, h = signal.freqs(b, a, worN=w)
gain_db_ana = 20 * np.log10(np.abs(h))
phase_deg_ana = np.degrees(np.angle(h))
# unwrap analytical phase in radians first, then to degrees, matching the
# continuous (non-wrapped) phase ngspice reports for a stable all-pole filter
phase_deg_ana = np.degrees(np.unwrap(np.angle(h)))
phase_deg_sim_unwrapped = np.degrees(np.unwrap(np.radians(phase_deg_sim)))

# hollow markers (open circles) for the simulated points, so the analytical
# line drawn underneath remains visible through the marker instead of being
# fully occluded by a filled dot -- the two curves overlap almost exactly.
# Subsampled too: at full density (301 pts over 6 decades) neighboring open
# circles still overlap enough to look like a solid band.
sim_marker = dict(marker="o", ms=5, mfc="none", mec="tab:blue", mew=1.2, linestyle="none")
ac_stride = max(1, len(freq) // 60)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(6.5, 6.5), sharex=True)
ax1.semilogx(freq, gain_db_ana, "-", lw=2, color="tab:orange", label="scipy (analytical)", zorder=2)
ax1.semilogx(freq[::ac_stride], gain_db_sim[::ac_stride], label="ngspice/OpenVAF", zorder=3, **sim_marker)
ax1.axvline(FC_HZ, color="gray", ls=":", lw=1, label=f"fc = {FC_HZ:.0f} Hz")
ax1.set_ylabel("Gain [dB]")
ax1.set_title(f"5th-order Bessel LPF ({N} poles, fc={FC_HZ:.0f} Hz) -- AC response")
ax1.grid(True, which="both")
ax1.legend()

ax2.semilogx(freq, phase_deg_ana, "-", lw=2, color="tab:orange", label="scipy (analytical)", zorder=2)
ax2.semilogx(
    freq[::ac_stride], phase_deg_sim_unwrapped[::ac_stride], label="ngspice/OpenVAF", zorder=3, **sim_marker
)
ax2.axvline(FC_HZ, color="gray", ls=":", lw=1)
ax2.set_ylabel("Phase [deg]")
ax2.set_xlabel("Frequency [Hz]")
ax2.grid(True, which="both")
plt.tight_layout()
plt.savefig("ac_compare.png", dpi=150)
plt.close()

gain_err = np.abs(gain_db_sim - gain_db_ana)
phase_err = np.abs(phase_deg_sim_unwrapped - phase_deg_ana)
print(f"AC: max |gain error|  = {gain_err.max():.3e} dB  (mean {gain_err.mean():.3e} dB)")
print(f"AC: max |phase error| = {phase_err.max():.3e} deg (mean {phase_err.mean():.3e} deg)")

# --- Transient: ngspice step response vs. scipy.signal.step -----------------
tran = np.loadtxt("tran.txt")
t_sim = tran[:, 0]
in_sim = tran[:, 1]
out_sim = tran[:, 3]

# ngspice's adaptive timestep doesn't give exactly-uniform samples even for a
# fixed .tran step, but scipy.signal.lsim (used by step()) requires one -- so
# resample onto a uniform grid first.
t_uniform = np.linspace(t_sim[0], t_sim[-1], len(t_sim))
out_sim_uniform = np.interp(t_uniform, t_sim, out_sim)
t_ana, out_ana = signal.step((b, a), T=t_uniform)

# subsample the (very dense, ~2us-spaced) simulated markers so individual
# hollow circles stay distinguishable instead of forming a solid ring that
# again hides the analytical line -- the line itself still uses every point.
marker_stride = max(1, len(t_sim) // 150)

plt.figure(figsize=(6.5, 4.5))
plt.plot(t_sim * 1e3, in_sim, "k--", lw=1, label="V(in) (step)")
plt.plot(t_ana * 1e3, out_ana, "-", lw=2, color="tab:orange", label="scipy (analytical)", zorder=2)
plt.plot(
    t_sim[::marker_stride] * 1e3,
    out_sim[::marker_stride],
    label="ngspice/OpenVAF",
    zorder=3,
    **sim_marker,
)
plt.xlabel("Time [ms]")
plt.ylabel("Voltage [V]")
plt.title(f"5th-order Bessel LPF (fc={FC_HZ:.0f} Hz) -- step response")
plt.grid(True)
plt.legend()
plt.tight_layout()
plt.savefig("tran_compare.png", dpi=150)
plt.close()

step_err = np.abs(out_sim_uniform - out_ana)
print(f"Step: max |error| = {step_err.max():.3e} V (mean {step_err.mean():.3e} V)")

print("wrote ac_compare.png, tran_compare.png")
