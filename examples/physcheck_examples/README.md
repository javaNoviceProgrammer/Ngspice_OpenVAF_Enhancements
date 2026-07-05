# physcheck_examples — physics-accuracy validation suite (Enhancement-57)

Validates that industry compact models compiled by the committed
`openvaf-r` reproduce **analytic device physics** in ngspice — a permanent,
quantitative regression guard over the whole toolchain: lowering, autodiff
Jacobians, the AC/small-signal path, and the noise pipeline. The models come
from the `VA_TEST` corpus (checks are skipped if it is absent).

## The five laws checked

1. **r2_cmc (CMC resistor)** — default resistance exactly 100 Ω, and its
   thermal noise spectrum **identical to a built-in ngspice resistor** of
   the same value: both are 4kT/R, so the Verilog-A noise path is
   cross-checked against ngspice's own with no physical constants assumed.
2. **diode_cmc** — the forward I-V ideal region (V ≈ 0.96–1.0 V at
   defaults; below that the CMC recombination/TAT components dominate by
   design) follows the junction law with ideality n ∈ [1.0, 1.06] — the
   **60 mV/decade** law (measured: 1.004–1.009).
3. **MEXTRAM bjt505** — Gummel plot at Vce = 1 V: collector-current
   ideality ∈ [1.0, 1.02] over Vbe 0.5–0.7 V, plausible positive β.
4. **PSP103** — **gm and gds from AC small-signal analysis equal the
   numeric derivatives of the DC curves** (5-point stencil), in triode and
   saturation. This cross-validates the **autodiff Jacobian against the
   residual** on a flagship compact model — agreement at the
   finite-difference floor (≈ 3–6 × 10⁻⁵ relative).
5. **JUNCAP200** — C(V) from the AC imaginary part obeys the junction
   grading law C = C₀/(1+V_R/V_bi)^0.5 *self-consistently*: V_bi fitted
   from C(0)/C(1) predicts C(0)/C(2) to 1.2 × 10⁻⁴, and the zero-bias
   capacitance matches the defaults (3 fF).

## Run

```
python3 verify_physcheck.py    # the 13 pass/fail checks
python3 plot_physcheck.py      # regenerates plots/*.png (needs matplotlib)
```

## Plots

`plot_physcheck.py` renders the five laws from dense sweeps into `plots/`:

| file | shows |
|---|---|
| `plots/diode_iv.png` | diode_cmc forward I–V on log scale with the ideal 60 mV/dec reference and a local-ideality panel (the recombination plateau below 0.9 V is the model's own physics) |
| `plots/gummel.png` | MEXTRAM 505 Gummel plot (I_C, I_B, β) with the ideal-slope reference |
| `plots/psp_gm.png` | PSP103 g_m(V_GS): the AC small-signal points (autodiff Jacobian) sitting exactly on the numeric derivative of the DC sweep |
| `plots/juncap_cv.png` | JUNCAP200 C(V) with the fitted junction grading law through every point |
| `plots/r2_noise.png` | the Verilog-A and built-in-resistor thermal-noise spectra coinciding (max relative difference ~7 × 10⁻⁷) |

13 checks, ALL PASS. No toolchain changes were needed — Enhancement-57 is a
validation deliverable: the compiled BJT, MOSFET, diode, junction, and
resistor models all reproduce their textbook laws quantitatively.
