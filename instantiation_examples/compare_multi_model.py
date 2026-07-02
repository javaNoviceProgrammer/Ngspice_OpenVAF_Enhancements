"""Cross-checks dc_sim_multi_model.cir, which demonstrates that ONE .osdi
file (compiled from resistor_divider.va, which declares three top-level
modules: resistor, buffer, divider) exposes every one of them as an
independently instantiable SPICE `.model` -- not just "divider", the one
used everywhere else in this directory.

This is a second, complementary form of hierarchy: Enhancement-5's
Verilog-A-level `instantiate` statement inlines sub-modules at *compile
time*, inside a single OSDI descriptor. This example instead composes two
*separately* compiled OSDI descriptors (`buffer` and `divider`, both from
the same .osdi) at the *netlist* level, exactly like any other pair of
SPICE devices:

  Vin --[buffer, standalone instance]-- mid --[divider, standalone instance]-- out (-> gnd=0)

`buffer` presents a 1 ohm resistance (its own internal `resistor #(.r(1))`
instance -- Enhancement-5 hierarchy, unrelated to this file-level
composition). `divider`'s own "in" pin only ever connects onward through
its internal in->out->gnd chain, so from the *outside* it behaves as a
single input resistance `R_A + R_B` (the same two combined values used
throughout this directory). Chaining the two standalone SPICE instances in
series therefore forms an ordinary two-resistor voltage divider between
`in` and `mid`, on top of `divider`'s own internal in->out ratio -- a
independent, hand-derivable prediction distinct from (but built out of)
the same building blocks as resistor_divider.va.

Run `ngspice -b dc_sim_multi_model.cir` first to (re)generate
dc_multi_model.txt.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

R_BUFFER = 1.0  # buffer's own internal resistor (standalone SPICE instance)
R_A = 1 / (1 / 1.0 + 1 / 1e3)  # divider's internal buffer(1) || r1(1e3), in->out
R_B = 1 / (1 / 2e3 + 1 / 1e3 + 1 / 1e3)  # divider's internal r2 || rarr[0] || rarr[1], out->gnd
R_DIVIDER_INPUT = R_A + R_B  # divider's total input resistance, seen from "mid"

RATIO_MID = R_DIVIDER_INPUT / (R_BUFFER + R_DIVIDER_INPUT)  # Vin -> mid
RATIO_INTERNAL = R_B / (R_A + R_B)  # divider's own in -> out ratio (== RATIO in the other scripts)
RATIO_OUT = RATIO_MID * RATIO_INTERNAL  # Vin -> out, end to end


def main() -> None:
    data = np.loadtxt("dc_multi_model.txt")
    vin, mid_sim, out_sim = data[:, 0], data[:, 3], data[:, 5]
    mid_expected = vin * RATIO_MID
    out_expected = vin * RATIO_OUT

    max_mid_err = np.max(np.abs(mid_sim - mid_expected))
    max_out_err = np.max(np.abs(out_sim - out_expected))

    print(f"R_buffer = {R_BUFFER:.6f} ohm, R_divider_input = {R_DIVIDER_INPUT:.6f} ohm")
    print(f"ratio Vin->mid = {RATIO_MID:.8f}, ratio Vin->out = {RATIO_OUT:.8f}")
    print(f"{'Vin':>8}  {'V(mid) sim':>14}  {'V(mid) exp':>14}  {'V(out) sim':>14}  {'V(out) exp':>14}")
    for v, m_s, m_e, o_s, o_e in zip(vin, mid_sim, mid_expected, out_sim, out_expected):
        print(f"{v:8.3f}  {m_s:14.8f}  {m_e:14.8f}  {o_s:14.8f}  {o_e:14.8f}")
    print(f"\nmax |V(mid) sim - expected| = {max_mid_err:.3e}")
    print(f"max |V(out) sim - expected| = {max_out_err:.3e}")
    assert max_mid_err < 1e-6, "V(mid) diverges from the analytical prediction"
    assert max_out_err < 1e-6, "V(out) diverges from the analytical prediction"

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))

    ax1.plot(vin, mid_expected, "-", lw=2, color="tab:orange", label="V(mid) analytical", zorder=2)
    ax1.plot(vin, mid_sim, "o", mfc="none", mec="tab:blue", mew=1.5, ms=7, label="V(mid) ngspice/OpenVAF", zorder=3)
    ax1.plot(vin, out_expected, "-", lw=2, color="tab:green", label="V(out) analytical", zorder=2)
    ax1.plot(vin, out_sim, "s", mfc="none", mec="tab:red", mew=1.5, ms=7, label="V(out) ngspice/OpenVAF", zorder=3)
    ax1.set_xlabel("V(in) [V]")
    ax1.set_ylabel("Voltage [V]")
    ax1.set_title("V(mid), V(out) vs V(in)")
    ax1.grid(True)
    ax1.legend()

    # V(mid) and V(out) sit close together at this scale (ratios 0.9975 vs
    # 0.9950) -- the drop across the standalone `buffer` instance, isolated
    # by itself, makes the two-stage composition visually obvious.
    drop_expected = mid_expected - out_expected
    drop_sim = mid_sim - out_sim
    ax2.plot(vin, drop_expected, "-", lw=2, color="tab:purple", label="analytical", zorder=2)
    ax2.plot(vin, drop_sim, "d", mfc="none", mec="tab:purple", mew=1.5, ms=7, label="ngspice/OpenVAF", zorder=3)
    ax2.set_xlabel("V(in) [V]")
    ax2.set_ylabel("V(mid) - V(out) [V]")
    ax2.set_title("Drop across divider's own in->out ratio")
    ax2.grid(True)
    ax2.legend()

    fig.suptitle("Two standalone instances (buffer + divider) from one .osdi")
    plt.tight_layout()
    plt.savefig("dc_multi_model.png", dpi=150)
    plt.close()

    print("\nOK: both standalone SPICE instances, from the same .osdi, compose correctly.")


if __name__ == "__main__":
    main()
