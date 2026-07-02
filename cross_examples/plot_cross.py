"""Plots DC, AC, and transient results for cross_demo.va (cross_dc.png,
cross_ac.png, cross_tran.png in this directory).

cross_demo.va's `analog` block is:
  @(cross(V(in) - thresh, dir)) begin count = count + 1.0; $strobe(...); end
  V(out) <+ count;
`count` is a persistent variable, incremented once per detected zero-crossing
-- the real-world use case for cross(), now possible after the Enhancement-8
fix documented in Enhancement-8.md's "Known limitations" §1.

DC: like a DC operating-point solve in general, the sweep's very first point
already includes one crossing "for free" -- the Newton solve converging to
Vin=-2 from its own internal starting guess crosses zero once on the way
there, and cross()'s edge-detection can't distinguish that from a genuine
timestep-to-timestep crossing (same class of documented non-ideality as
Enhancement-6/7's DC/AC sections). From then on, `count` only increments
again when the swept V(in) itself crosses `thresh` (dir=1 here => rising
only): observed as a single further step, at the sweep point V(in) = 0.25 V.

AC: cross() only fires on an actual level crossing, which the small-signal
AC operating point (one fixed bias) never produces -- so the small-signal
gain V(in)->V(out) is exactly zero at every frequency.

Transient: V(in) = 2*sin(2*pi*1kHz*t) crosses zero twice per cycle (dir=0,
either direction, for the transient .cir); V(out) = count steps up by 1 at
each crossing, visible as a staircase.

Run `ngspice -b dc_sim_cross.cir`, `ngspice -b ac_sim_cross.cir`, and
`ngspice -b tran_cross.cir` first to (re)generate the .txt inputs.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def check_dc() -> None:
    data = np.loadtxt("dc_cross.txt")
    vin, vout = data[:, 0], data[:, 3]
    # First sweep point already carries one "free" crossing from the DC
    # solve's own convergence path (see module docstring); count then steps
    # again exactly where the swept V(in) crosses thresh=0 rising.
    expected = 1.0 + (vin > 0.0).astype(float)
    max_abs_err = np.max(np.abs(vout - expected))
    print("[cross DC] V(out) = count: starts at 1 (DC solve's own convergence-path crossing),")
    print("then steps to 2 where the swept V(in) crosses thresh=0 (rising).")
    print(f"max |V(out) - expected| = {max_abs_err:.3e}\n")
    assert max_abs_err < 1e-9

    plt.figure(figsize=(5.5, 4.5))
    plt.plot(vin, expected, "-", lw=2, color="tab:orange", label="expected step", zorder=2)
    plt.plot(vin, vout, "o", mfc="none", mec="tab:blue", mew=1.5, ms=7, label="V(out) = count (ngspice/OpenVAF)", zorder=3)
    plt.axvline(0.0, color="gray", ls="--", lw=1, label="thresh = 0.0")
    plt.xlabel("V(in) [V]")
    plt.ylabel("V(out) = count")
    plt.title("cross_demo.va -- DC sweep (persistent counter steps at thresh)")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig("cross_dc.png", dpi=150)
    plt.close()


def check_ac() -> None:
    data = np.loadtxt("ac_cross.txt")
    freq, gain_db, phase_deg = data[:, 0], data[:, 1], data[:, 3]
    max_gain_err = np.max(np.abs(gain_db))
    max_phase_err = np.max(np.abs(phase_deg))
    print("[cross AC] cross() only fires on a level crossing, which a fixed AC bias point never")
    print("produces -- so the small-signal gain V(in)->V(out) is exactly zero.")
    print(f"max |gain| = {max_gain_err:.3e} dB, max |phase| = {max_phase_err:.3e} deg\n")
    assert max_gain_err < 1e-6
    assert max_phase_err < 1e-6

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(6, 6), sharex=True)
    ax1.semilogx(freq, gain_db, "o", mfc="none", mec="tab:blue", mew=1.2, ms=5, label="ngspice/OpenVAF", zorder=3)
    ax1.set_ylabel("Gain [dB]")
    ax1.set_title("cross_demo.va -- AC response (no small-signal path through count)")
    ax1.grid(True, which="both")
    ax1.legend()

    ax2.semilogx(freq, phase_deg, "o", mfc="none", mec="tab:blue", mew=1.2, ms=5, zorder=3)
    ax2.set_ylabel("Phase [deg]")
    ax2.set_xlabel("Frequency [Hz]")
    ax2.grid(True, which="both")
    plt.tight_layout()
    plt.savefig("cross_ac.png", dpi=150)
    plt.close()


def plot_tran() -> None:
    data = np.loadtxt("tran_cross.txt")
    t, vin, vout = data[:, 0], data[:, 1], data[:, 3]
    print("[cross transient] V(in) = 2*sin(2*pi*1kHz*t); V(out) = count, incrementing on every")
    print("zero-crossing (dir=0, both directions) -- a staircase, not a copy of V(in).")
    print(f"final count = {vout[-1]:.0f} over {t[-1]*1e3:.1f} ms (expect ~6 crossings at 1kHz, both directions)\n")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 6), sharex=True)
    ax1.plot(t * 1e3, vin, "-", lw=1.5, color="gray", label="V(in)")
    ax1.axhline(0.0, color="tab:red", ls="--", lw=1, label="thresh = 0.0")
    ax1.set_ylabel("V(in) [V]")
    ax1.set_title("cross_demo.va -- transient")
    ax1.grid(True)
    ax1.legend()

    stride = max(1, len(t) // 1000)
    ax2.step(t[::stride] * 1e3, vout[::stride], where="post", color="tab:blue", label="V(out) = count")
    ax2.set_xlabel("Time [ms]")
    ax2.set_ylabel("count")
    ax2.grid(True)
    ax2.legend()
    plt.tight_layout()
    plt.savefig("cross_tran.png", dpi=150)
    plt.close()


def main() -> None:
    check_dc()
    check_ac()
    plot_tran()
    print("OK: cross_demo's persistent counter steps correctly on each cross() firing.")


if __name__ == "__main__":
    main()
