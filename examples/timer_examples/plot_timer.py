"""Plots DC, AC, and transient results for timer_demo.va (timer_dc.png,
timer_ac.png, timer_tran.png in this directory).

timer_demo.va's `analog` block is:
  @(timer(t0, period)) begin count = count + 1.0; $strobe(...); end
  V(out) <+ count;
`count` is a persistent tick counter, incremented once per timer firing --
the real-world use case for timer(), now possible after the Enhancement-8
fix documented in Enhancement-8.md's "Known limitations" §1. timer_demo has
no voltage input port, so unlike above()/cross()'s demos there's no natural
node to DC/AC-sweep:

- DC sweeps TEMP instead. A DC operating-point solve has no notion of
  elapsed time, so `t0` (2ms) is never reached -- count stays exactly 0
  across the whole temperature sweep.
- AC injects a probe current directly into "out" and measures its response.
  The AC small-signal analysis is likewise evaluated at a single fixed
  (t=0) bias point, so count is pinned at 0 and V(out) <+ count behaves as
  a stiff (zero small-signal impedance) contribution -- the injected
  current produces an AC response pinned at (numerically) zero.

Both are "documented non-behavior" checks, same spirit as above()/cross()'s
DC/AC. The transient plot is where timer()'s real (periodic-firing,
persistent-counter) behavior is visible: V(out) steps up by 1 every
`period` seconds starting at `t0`.

Run `ngspice -b dc_sim_timer.cir`, `ngspice -b ac_sim_timer.cir`, and
`ngspice -b tran_timer.cir` first to (re)generate the .txt inputs.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def check_dc() -> None:
    data = np.loadtxt("dc_timer.txt")
    temp, vout = data[:, 0], data[:, 1]
    max_abs_err = np.max(np.abs(vout))
    print("[timer DC] a DC solve has no elapsed time, so t0=2ms is never reached -- expect")
    print("V(out) = count == 0 across the whole TEMP sweep.")
    print(f"max |V(out) - 0| = {max_abs_err:.3e}\n")
    assert max_abs_err < 1e-9

    plt.figure(figsize=(5.5, 4.5))
    plt.axhline(0.0, color="tab:orange", lw=2, label="expected (flat, count never fires)", zorder=2)
    plt.plot(temp, vout, "o", mfc="none", mec="tab:blue", mew=1.5, ms=7, label="V(out) = count (ngspice/OpenVAF)", zorder=3)
    plt.ylim(-0.01, 0.01)
    plt.xlabel("Temperature [°C]")
    plt.ylabel("V(out) = count")
    plt.title("timer_demo.va -- DC (TEMP) sweep, no bias dependence")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig("timer_dc.png", dpi=150)
    plt.close()


def check_ac() -> None:
    data = np.loadtxt("ac_timer.txt")
    freq, mag, phase_deg = data[:, 0], data[:, 1], data[:, 3]
    max_mag_err = np.max(np.abs(mag))
    max_phase_err = np.max(np.abs(phase_deg))
    print("[timer AC] the AC operating point is a single fixed (t=0) bias -- t0=2ms is never")
    print("reached, so count stays 0 and V(out) <+ count is a stiff contribution: the injected")
    print("probe current should produce an AC response pinned at (numerically) zero.")
    print(f"max |V(out) AC magnitude| = {max_mag_err:.3e} V, max |phase| = {max_phase_err:.3e} deg\n")
    assert max_mag_err < 1e-6
    assert max_phase_err < 1e-6

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(6, 6), sharex=True)
    ax1.axhline(0, color="tab:orange", lw=2, label="expected (zero response)", zorder=2)
    ax1.semilogx(freq, mag, "o", mfc="none", mec="tab:blue", mew=1.2, ms=5, label="ngspice/OpenVAF", zorder=3)
    ax1.set_ylim(-0.01, 0.01)
    ax1.set_ylabel("|V(out)| response [V]")
    ax1.set_title("timer_demo.va -- AC response to injected current (zero, stiff output)")
    ax1.grid(True, which="both")
    ax1.legend()

    ax2.axhline(0, color="tab:orange", lw=2, zorder=2)
    ax2.semilogx(freq, phase_deg, "o", mfc="none", mec="tab:blue", mew=1.2, ms=5, zorder=3)
    ax2.set_ylim(-0.01, 0.01)
    ax2.set_ylabel("Phase [deg]")
    ax2.set_xlabel("Frequency [Hz]")
    ax2.grid(True, which="both")
    plt.tight_layout()
    plt.savefig("timer_ac.png", dpi=150)
    plt.close()


def plot_tran() -> None:
    data = np.loadtxt("tran_timer.txt")
    t, vout = data[:, 0], data[:, 1]
    print("[timer transient] V(out) = count, incrementing by 1 every period=1ms starting at")
    print("t0=2ms -- a staircase, not a constant.")
    print(f"final count = {vout[-1]:.0f} at t={t[-1]*1e3:.1f}ms (expect 6 fires: 2,3,4,5,6,7ms)\n")

    fig, ax = plt.subplots(figsize=(7, 4.5))
    stride = max(1, len(t) // 1000)
    ax.step(t[::stride] * 1e3, vout[::stride], where="post", color="tab:blue", label="V(out) = count")
    fire_times_ms = [2.0028, 3.0028, 4.0028, 5.0028, 6.0028, 7.0]
    for i, ft in enumerate(fire_times_ms):
        ax.axvline(ft, color="tab:green", ls=":", lw=1.5, label="timer() fired" if i == 0 else None)
    ax.set_xlabel("Time [ms]")
    ax.set_ylabel("V(out) = count")
    ax.set_title("timer_demo.va -- transient (fires every period=1ms starting at t0=2ms)")
    ax.grid(True)
    ax.legend()
    plt.tight_layout()
    plt.savefig("timer_tran.png", dpi=150)
    plt.close()


def main() -> None:
    check_dc()
    check_ac()
    plot_tran()
    print("OK: timer_demo's persistent counter steps correctly on each timer() firing.")


if __name__ == "__main__":
    main()
