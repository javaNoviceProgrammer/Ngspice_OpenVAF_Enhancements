"""Cross-checks resistor_divider_include.va -- the exact same network as
resistor_divider.va, except `resistor`/`buffer` are defined in a separate
file (resistor_lib.va) and pulled in via `` `include ``, confirming module
instantiation works across an `` `include `` boundary and not just for
modules declared in the same file. Since the elaboration pass reads from
the already-`` `include ``-expanded parse tree (`` `include `` is resolved
by the preprocessor before elaboration ever runs), the flattened circuit
-- and therefore every result here -- is identical to resistor_divider.va.

Run `ngspice -b dc_sim_include.cir`, `ngspice -b ac_sim_include.cir`,
`ngspice -b tran_sim_include.cir` first to (re)generate
dc_include.txt/ac_include.txt/tran_include.txt.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

R_IN_OUT = 1 / (1 / 1.0 + 1 / 1e3)  # buffer (1 ohm) || r1 (1e3 ohm)
R_OUT_GND = 1 / (1 / 2e3 + 1 / 1e3 + 1 / 1e3)  # r2 || rarr[0] || rarr[1]
RATIO = R_OUT_GND / (R_IN_OUT + R_OUT_GND)


def expected_vout(vin) -> np.ndarray:
    return vin * RATIO


def check_dc() -> None:
    data = np.loadtxt("dc_include.txt")
    vin, vout_sim = data[:, 0], data[:, 3]
    vout_expected = expected_vout(vin)
    max_abs_err = np.max(np.abs(vout_sim - vout_expected))

    print(f"ratio = {RATIO:.8f}")
    print("[DC]")
    for v_in, v_sim, v_exp in zip(vin, vout_sim, vout_expected):
        print(f"{v_in:8.3f}  sim={v_sim:14.8f}  expected={v_exp:14.8f}  err={abs(v_sim - v_exp):10.2e}")
    print(f"max |sim - expected| = {max_abs_err:.3e}\n")
    assert max_abs_err < 1e-6, "DC: diverges from the analytical prediction"

    plt.figure(figsize=(5.5, 4.5))
    plt.plot(vin, vout_expected, "-", lw=2, color="tab:orange", label="analytical", zorder=2)
    plt.plot(vin, vout_sim, "o", mfc="none", mec="tab:blue", mew=1.5, ms=7, label="ngspice/OpenVAF", zorder=3)
    plt.xlabel("V(in) [V]")
    plt.ylabel("V(out) [V]")
    plt.title(f"resistor_divider_include.va -- DC sweep (ratio = {RATIO:.6f})")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig("dc_include.png", dpi=150)
    plt.close()


def check_ac() -> None:
    data = np.loadtxt("ac_include.txt")
    freq, gain_db_sim, phase_deg_sim = data[:, 0], data[:, 1], data[:, 3]
    gain_db_expected = 20 * np.log10(RATIO)

    max_gain_err = np.max(np.abs(gain_db_sim - gain_db_expected))
    max_phase_err = np.max(np.abs(phase_deg_sim))
    print("[AC]")
    print(f"max |gain sim - expected| = {max_gain_err:.3e} dB")
    print(f"max |phase sim - expected| = {max_phase_err:.3e} deg\n")
    assert max_gain_err < 1e-3, "AC: gain diverges from the flat analytical prediction"
    assert max_phase_err < 1e-3, "AC: phase diverges from the flat (zero) analytical prediction"

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(6, 6), sharex=True)
    ax1.axhline(gain_db_expected, color="tab:orange", lw=2, label="analytical (flat)", zorder=2)
    ax1.semilogx(freq, gain_db_sim, "o", mfc="none", mec="tab:blue", mew=1.2, ms=5, label="ngspice/OpenVAF", zorder=3)
    ax1.set_ylim(gain_db_expected - 0.01, gain_db_expected + 0.01)
    ax1.set_ylabel("Gain [dB]")
    ax1.set_title("resistor_divider_include.va -- AC response")
    ax1.grid(True, which="both")
    ax1.legend()

    ax2.axhline(0, color="tab:orange", lw=2, zorder=2)
    ax2.semilogx(freq, phase_deg_sim, "o", mfc="none", mec="tab:blue", mew=1.2, ms=5, zorder=3)
    ax2.set_ylim(-0.01, 0.01)
    ax2.set_ylabel("Phase [deg]")
    ax2.set_xlabel("Frequency [Hz]")
    ax2.grid(True, which="both")
    plt.tight_layout()
    plt.savefig("ac_include.png", dpi=150)
    plt.close()


def check_tran() -> None:
    data = np.loadtxt("tran_include.txt")
    t, vin_t, vout_sim_t = data[:, 0], data[:, 1], data[:, 3]
    vout_expected_t = expected_vout(vin_t)

    max_abs_err = np.max(np.abs(vout_sim_t - vout_expected_t))
    print("[Transient] (1 kHz, 2 V amplitude sine drive)")
    print(f"max |V(out) sim - ratio*V(in) sim| = {max_abs_err:.3e}\n")
    assert max_abs_err < 1e-6, "Transient: V(out) doesn't track ratio*V(in) pointwise"

    plt.figure(figsize=(6.5, 4.5))
    plt.plot(t * 1e3, vin_t, "-", lw=1.5, color="gray", label="V(in)", zorder=2)
    plt.plot(t * 1e3, vout_expected_t, "-", lw=2, color="tab:orange", label="V(out) analytical", zorder=3)
    stride = max(1, len(t) // 60)
    plt.plot(
        t[::stride] * 1e3,
        vout_sim_t[::stride],
        "o",
        mfc="none",
        mec="tab:blue",
        mew=1.2,
        ms=5,
        label="V(out) ngspice/OpenVAF",
        zorder=4,
    )
    plt.xlabel("Time [ms]")
    plt.ylabel("Voltage [V]")
    plt.title("resistor_divider_include.va -- transient response")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig("tran_include.png", dpi=150)
    plt.close()


def main() -> None:
    check_dc()
    check_ac()
    check_tran()
    print("OK: DC, AC, and transient all match resistor_divider.va (as expected, same flattened circuit).")


if __name__ == "__main__":
    main()
