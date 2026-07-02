"""Plots DC, AC, and transient results for above_demo.va (above_dc.png,
above_ac.png, above_tran.png in this directory).

above_demo.va's `analog` block is:
  @(above(V(in) - thresh)) begin count = count + 1.0; $strobe(...); end
  V(out) <+ count;
`count` is a persistent variable, incremented once per rising edge through
`thresh` (edge-triggered, not level-triggered) -- this is the real-world use
case for above(), now possible after the Enhancement-8 fix documented in
Enhancement-8.md's "Known limitations" §1 (`mir_opt::simplify_cfg`'s
`merge_block_into_predecessor` losing track of the function's true exit
block after a block merge).

DC: V(out) is a step function of the swept V(in) -- 0 while V(in) < thresh,
jumping to 1 exactly at the sweep point where V(in) first crosses thresh,
and staying there (persistent state carries across DC sweep points the same
way it carries across transient timesteps).

AC: above() only fires on a level crossing, which the small-signal AC
operating point (a single fixed bias) does not have -- so the AC gain from
V(in) to V(out) is exactly zero at every frequency (V(out) sees no small-
signal component of V(in) at all, only the accumulated count from the DC
operating point).

Transient: V(in) = 2*sin(2*pi*1kHz*t) crosses thresh = 1.0 once per cycle;
V(out) steps up by 1 at each crossing, visible as a staircase.

Run `ngspice -b dc_sim_above.cir`, `ngspice -b ac_sim_above.cir`, and
`ngspice -b tran_above.cir` first (using version9's own openvaf-r/ngspice)
to (re)generate dc_above.txt / ac_above.txt / tran_above.txt.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def check_dc() -> None:
    data = np.loadtxt("dc_above.txt")
    vin, vout = data[:, 0], data[:, 3]
    thresh = 1.0
    expected = (vin > thresh).astype(float)
    max_abs_err = np.max(np.abs(vout - expected))
    print("[above DC] V(out) = count, a step function that goes 0 -> 1 the sweep point after V(in) exceeds thresh.")
    print(f"max |V(out) - step(V(in)>thresh)| = {max_abs_err:.3e}\n")
    assert max_abs_err < 1e-9, "above DC: count step does not land where V(in) crosses thresh"

    plt.figure(figsize=(5.5, 4.5))
    plt.plot(vin, expected, "-", lw=2, color="tab:orange", label="expected step", zorder=2)
    plt.plot(vin, vout, "o", mfc="none", mec="tab:blue", mew=1.5, ms=7, label="V(out) = count (ngspice/OpenVAF)", zorder=3)
    plt.axvline(thresh, color="gray", ls="--", lw=1, label=f"thresh = {thresh}")
    plt.xlabel("V(in) [V]")
    plt.ylabel("V(out) = count")
    plt.title("above_demo.va -- DC sweep (persistent counter steps at thresh)")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig("above_dc.png", dpi=150)
    plt.close()


def check_ac() -> None:
    data = np.loadtxt("ac_above.txt")
    freq, gain_db, phase_deg = data[:, 0], data[:, 1], data[:, 3]
    print("[above AC] above() only fires on a level crossing, which a fixed AC bias point never")
    print("produces -- so the small-signal gain V(in)->V(out) is exactly zero (V(out) is pinned")
    print("at whatever `count` reached during the DC operating point).")
    max_gain_err = np.max(np.abs(gain_db))
    max_phase_err = np.max(np.abs(phase_deg))
    print(f"max |gain| = {max_gain_err:.3e} dB, max |phase| = {max_phase_err:.3e} deg\n")
    assert max_gain_err < 1e-6
    assert max_phase_err < 1e-6

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(6, 6), sharex=True)
    ax1.semilogx(freq, gain_db, "o", mfc="none", mec="tab:blue", mew=1.2, ms=5, label="ngspice/OpenVAF", zorder=3)
    ax1.set_ylabel("Gain [dB]")
    ax1.set_title("above_demo.va -- AC response (no small-signal path through count)")
    ax1.grid(True, which="both")
    ax1.legend()

    ax2.semilogx(freq, phase_deg, "o", mfc="none", mec="tab:blue", mew=1.2, ms=5, zorder=3)
    ax2.set_ylabel("Phase [deg]")
    ax2.set_xlabel("Frequency [Hz]")
    ax2.grid(True, which="both")
    plt.tight_layout()
    plt.savefig("above_ac.png", dpi=150)
    plt.close()


def plot_tran() -> None:
    data = np.loadtxt("tran_above.txt")
    t, vin, vout = data[:, 0], data[:, 1], data[:, 3]
    thresh = 1.0
    print("[above transient] V(in) = 2*sin(2*pi*1kHz*t); V(out) = count, incrementing once per")
    print("rising crossing of thresh (a staircase, not a copy of V(in)).")
    print(f"final count = {vout[-1]:.0f} over {t[-1]*1e3:.1f} ms (expect ~3 rising crossings at 1kHz)\n")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 6), sharex=True)
    ax1.plot(t * 1e3, vin, "-", lw=1.5, color="gray", label="V(in)")
    ax1.axhline(thresh, color="tab:red", ls="--", lw=1, label=f"thresh = {thresh}")
    ax1.set_ylabel("V(in) [V]")
    ax1.set_title("above_demo.va -- transient")
    ax1.grid(True)
    ax1.legend()

    stride = max(1, len(t) // 1000)
    ax2.step(t[::stride] * 1e3, vout[::stride], where="post", color="tab:blue", label="V(out) = count")
    ax2.set_xlabel("Time [ms]")
    ax2.set_ylabel("count")
    ax2.grid(True)
    ax2.legend()
    plt.tight_layout()
    plt.savefig("above_tran.png", dpi=150)
    plt.close()


def main() -> None:
    check_dc()
    check_ac()
    plot_tran()
    print("OK: above_demo's persistent counter steps correctly on each above() firing.")


if __name__ == "__main__":
    main()
