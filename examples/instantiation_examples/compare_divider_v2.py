"""Cross-checks the DC, AC, and transient simulations of
resistor_divider_v2.va, where `divider` both instantiates sub-modules
*and* has its own analog block (a direct resistor from `in` to `gnd`,
parallel to the whole in->out->gnd instantiated network), and plots all
three (dc_v2.png, ac_v2.png, tran_v2.png).

Topology (see resistor_divider_v2.va):
  in --[buffer: 1 ohm]-- out
  in --[r1: 1e3 ohm]---- out
  out --[r2: 2e3 ohm]--- gnd
  out --[rarr[0]: 1e3]-- gnd
  out --[rarr[1]: 1e3]-- gnd
  in --[r_direct: 5e3 ohm, divider's OWN analog block]-- gnd

With `gnd` tied to 0 and an ideal `Vin` driving `in`:
- V(out) is a plain two-resistor divider between the in->out and
  out->gnd combined resistances -- R_direct doesn't affect it at all,
  since it's a separate path directly from the (ideal, zero-impedance)
  source to ground, entirely bypassing node `out`.
- The *current drawn from Vin* does change: it's the sum of the current
  through the in->out->gnd path and the current through R_direct -- this
  is the signal that actually exercises the module's own directly-written
  analog block, since V(out) alone can't distinguish "r_direct present" vs
  "r_direct absent".
- Both paths are purely resistive, so AC gain/phase (of V(out)/V(in)) is
  frequency-independent and the transient response tracks the input
  instantaneously.

Run `ngspice -b dc_sim_v2.cir`, `ngspice -b ac_sim_v2.cir`, `ngspice -b
tran_sim_v2.cir` first to (re)generate dc_v2.txt/ac_v2.txt/tran_v2.txt.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

R_IN_OUT = 1 / (1 / 1.0 + 1 / 1e3)  # buffer (1 ohm) || r1 (1e3 ohm)
R_OUT_GND = 1 / (1 / 2e3 + 1 / 1e3 + 1 / 1e3)  # r2 || rarr[0] || rarr[1]
R_DIRECT = 5e3  # divider's own analog block
RATIO = R_OUT_GND / (R_IN_OUT + R_OUT_GND)


def expected_vout(vin) -> np.ndarray:
    return vin * RATIO


def expected_i_vin(vin) -> np.ndarray:
    # current into the instantiated network's path, plus current into the
    # direct path -- ngspice reports source current with the sign
    # convention that current flows out of the positive terminal into the
    # external circuit as *negative*, so match that sign.
    i_network = vin / (R_IN_OUT + R_OUT_GND)
    i_direct = vin / R_DIRECT
    return -(i_network + i_direct)


def check_dc() -> None:
    data = np.loadtxt("dc_v2.txt")
    vin, vout_sim, i_vin_sim = data[:, 0], data[:, 3], data[:, 5]
    vout_expected = expected_vout(vin)
    i_vin_expected = expected_i_vin(vin)

    max_v_err = np.max(np.abs(vout_sim - vout_expected))
    max_i_err = np.max(np.abs(i_vin_sim - i_vin_expected))

    print(f"R(in,out) = {R_IN_OUT:.6f} ohm, R(out,gnd) = {R_OUT_GND:.6f} ohm, R_direct = {R_DIRECT:.1f} ohm")
    print("[DC]")
    print(f"{'Vin':>8}  {'V(out) sim':>14}  {'V(out) exp':>14}  {'I(Vin) sim':>14}  {'I(Vin) exp':>14}")
    for v, vo_s, vo_e, i_s, i_e in zip(vin, vout_sim, vout_expected, i_vin_sim, i_vin_expected):
        print(f"{v:8.3f}  {vo_s:14.8f}  {vo_e:14.8f}  {i_s:14.8e}  {i_e:14.8e}")
    print(f"max |V(out) sim - expected| = {max_v_err:.3e}")
    print(f"max |I(Vin) sim - expected| = {max_i_err:.3e}\n")
    assert max_v_err < 1e-6, "DC: V(out) diverges from the analytical prediction"
    assert max_i_err < 1e-6, "DC: I(Vin) diverges from the analytical prediction"

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))
    ax1.plot(vin, vout_expected, "-", lw=2, color="tab:orange", label="analytical", zorder=2)
    ax1.plot(vin, vout_sim, "o", mfc="none", mec="tab:blue", mew=1.5, ms=7, label="ngspice/OpenVAF", zorder=3)
    ax1.set_xlabel("V(in) [V]")
    ax1.set_ylabel("V(out) [V]")
    ax1.set_title("V(out) -- unaffected by r_direct")
    ax1.grid(True)
    ax1.legend()

    ax2.plot(vin, i_vin_expected * 1e3, "-", lw=2, color="tab:orange", label="analytical", zorder=2)
    ax2.plot(vin, i_vin_sim * 1e3, "o", mfc="none", mec="tab:red", mew=1.5, ms=7, label="ngspice/OpenVAF", zorder=3)
    ax2.set_xlabel("V(in) [V]")
    ax2.set_ylabel("I(Vin) [mA]")
    ax2.set_title("I(Vin) -- network + r_direct combined")
    ax2.grid(True)
    ax2.legend()

    fig.suptitle("resistor_divider_v2.va -- DC sweep")
    plt.tight_layout()
    plt.savefig("dc_v2.png", dpi=150)
    plt.close()


def check_ac() -> None:
    data = np.loadtxt("ac_v2.txt")
    freq, gain_db_sim, phase_deg_sim = data[:, 0], data[:, 1], data[:, 3]
    gain_db_expected = 20 * np.log10(RATIO)
    phase_deg_expected = np.zeros_like(freq)

    max_gain_err = np.max(np.abs(gain_db_sim - gain_db_expected))
    max_phase_err = np.max(np.abs(phase_deg_sim - phase_deg_expected))
    print("[AC] (V(out)/V(in); r_direct doesn't touch this path)")
    print(f"expected flat gain = {gain_db_expected:.6f} dB, phase = 0 deg")
    print(f"max |gain sim - expected| = {max_gain_err:.3e} dB")
    print(f"max |phase sim - expected| = {max_phase_err:.3e} deg\n")
    assert max_gain_err < 1e-3, "AC: gain diverges from the flat analytical prediction"
    assert max_phase_err < 1e-3, "AC: phase diverges from the flat (zero) analytical prediction"

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(6, 6), sharex=True)
    ax1.axhline(gain_db_expected, color="tab:orange", lw=2, label="analytical (flat)", zorder=2)
    ax1.semilogx(freq, gain_db_sim, "o", mfc="none", mec="tab:blue", mew=1.2, ms=5, label="ngspice/OpenVAF", zorder=3)
    ax1.set_ylim(gain_db_expected - 0.01, gain_db_expected + 0.01)
    ax1.set_ylabel("Gain [dB]")
    ax1.set_title("resistor_divider_v2.va -- AC response, V(out)/V(in)")
    ax1.grid(True, which="both")
    ax1.legend()

    ax2.axhline(0, color="tab:orange", lw=2, zorder=2)
    ax2.semilogx(freq, phase_deg_sim, "o", mfc="none", mec="tab:blue", mew=1.2, ms=5, zorder=3)
    ax2.set_ylim(-0.01, 0.01)
    ax2.set_ylabel("Phase [deg]")
    ax2.set_xlabel("Frequency [Hz]")
    ax2.grid(True, which="both")
    plt.tight_layout()
    plt.savefig("ac_v2.png", dpi=150)
    plt.close()


def check_tran() -> None:
    data = np.loadtxt("tran_v2.txt")
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
    plt.title("resistor_divider_v2.va -- transient response")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig("tran_v2.png", dpi=150)
    plt.close()


def main() -> None:
    check_dc()
    check_ac()
    check_tran()
    print("OK: DC (V(out) and I(Vin)), AC, and transient all match the analytical prediction.")


if __name__ == "__main__":
    main()
