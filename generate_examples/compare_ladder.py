"""Cross-checks the OpenVAF/ngspice DC sweep of `resistor_ladder_generate.va`
(built with `generate for` / `genvar`) against the hand-written, non-generate
equivalent `resistor_ladder_manual.va`, and against an independent
analytical resistor-divider computation. Plots dc.png.

Topology (see resistor_ladder_generate.va): a 4-element `generate for` loop
produces a 4-resistor chain node[0]..node[4] (1 kohm each), bracketed by two
more hand-written resistors (rin, rout) -- 6 x 1 kohm = 6 kohm total series
resistance between `in` and `out`, loaded by Rload = 1 Mohm to ground. This
is an ordinary two-resistor voltage divider (6 kohm series vs. 1 Mohm load).

Run `ngspice -b dc_sim_generate.cir` and `ngspice -b dc_sim_manual.cir`
first (using version9's own openvaf-r/ngspice) to (re)generate
dc_generate.txt/dc_manual.txt.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

R_SERIES = 6 * 1e3  # rin + 4x generate-for resistors + rout
R_LOAD = 1e6
RATIO = R_LOAD / (R_SERIES + R_LOAD)


def expected_vout(vin) -> np.ndarray:
    return vin * RATIO


def main() -> None:
    gen = np.loadtxt("dc_generate.txt")
    man = np.loadtxt("dc_manual.txt")
    vin_g, vout_g = gen[:, 0], gen[:, 3]
    vin_m, vout_m = man[:, 0], man[:, 3]

    assert np.allclose(vin_g, vin_m), "generate/manual sweeps use different Vin points"
    max_gen_vs_man = np.max(np.abs(vout_g - vout_m))

    vout_expected = expected_vout(vin_g)
    max_gen_vs_analytical = np.max(np.abs(vout_g - vout_expected))

    print(f"R_series = {R_SERIES:.1f} ohm, R_load = {R_LOAD:.1f} ohm, ratio = {RATIO:.8f}")
    print(f"{'Vin':>8}  {'V(out) generate':>16}  {'V(out) manual':>14}  {'V(out) analytical':>18}")
    for v_in, v_g, v_m, v_e in zip(vin_g, vout_g, vout_m, vout_expected):
        print(f"{v_in:8.3f}  {v_g:16.8f}  {v_m:14.8f}  {v_e:18.8f}")
    print(f"\nmax |generate - manual|      = {max_gen_vs_man:.3e}  (should be exactly 0 -- bit-exact)")
    print(f"max |generate - analytical|  = {max_gen_vs_analytical:.3e}")

    assert max_gen_vs_man == 0.0, "generate-for ladder diverges from the hand-written equivalent"
    assert max_gen_vs_analytical < 1e-6, "generate-for ladder diverges from the analytical prediction"

    plt.figure(figsize=(5.5, 4.5))
    plt.plot(vin_g, vout_expected, "-", lw=2, color="tab:orange", label="analytical", zorder=2)
    plt.plot(vin_m, vout_m, "s", mfc="none", mec="tab:green", mew=1.5, ms=9, label="manual (hand-written)", zorder=3)
    plt.plot(vin_g, vout_g, "o", mfc="none", mec="tab:blue", mew=1.5, ms=6, label="generate for / genvar", zorder=4)
    plt.xlabel("V(in) [V]")
    plt.ylabel("V(out) [V]")
    plt.title(f"resistor ladder -- DC sweep (ratio = {RATIO:.6f})")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig("dc.png", dpi=150)
    plt.close()

    print("\nOK: generate-for ladder is bit-exact with the hand-written equivalent and")
    print("matches the analytical resistor-divider prediction.")


if __name__ == "__main__":
    main()
