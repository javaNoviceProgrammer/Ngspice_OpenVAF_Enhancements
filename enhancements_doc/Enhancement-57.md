# Enhancement-57 — physics-accuracy validation suite (version11)

This enhancement adds a permanent, quantitative **physics regression suite**
(`physcheck_examples/`) checking that industry compact models compiled by
OpenVAF-r reproduce **analytic device laws** in ngspice. Unlike E-56's
smoke sweep (does it run?), this validates *the numbers*. No toolchain
defects were found — the enhancement is the validation deliverable itself,
guarding lowering, autodiff, AC, and noise against future regressions.

## What is verified (all against closed-form physics)

| model | law | result |
|---|---|---|
| r2_cmc | thermal noise ≡ built-in ngspice resistor (4kT/R) | identical to < 10⁻⁶ |
| diode_cmc | junction law, 60 mV/decade in the ideal region | n = 1.004–1.009 |
| MEXTRAM bjt505 | Gummel slope + β | n = 1.012–1.017, β 73–159 |
| PSP103 | **AC gm/gds ≡ numeric d/dV of DC** (autodiff Jacobian vs residual) | 3–6 × 10⁻⁵ relative (finite-difference floor) |
| JUNCAP200 | C(V) grading law self-consistency | 1.2 × 10⁻⁴ |

## Notes from the probe

- diode_cmc below ~0.9 V is dominated by its recombination/TAT components
  at default lifetimes (apparent ideality 4–7) — that is the model's
  physics, not an artifact; the ideal region emerges at 0.96–1.0 V. A
  naive "check n≈1 at 0.3 V" would be wrong.
- The gds check in deep saturation is limited by finite-difference noise
  on a 35 nS conductance (12-digit prints); the triode-region check pins
  it tightly instead, and the saturation bound is set accordingly.
- The r2_cmc noise identity is constants-free: the same circuit is run
  with the Verilog-A resistor and ngspice's built-in resistor, and the
  spectra must be equal — whatever k·T ngspice uses.

`verify_physcheck.py`: 13/13 PASS. `plot_physcheck.py` renders the five
laws as PNG plots (`physcheck_examples/plots/`): the diode I–V with its
local-ideality panel, the Gummel plot, the PSP g_m AC-vs-numeric overlay,
the JUNCAP C(V) fit, and the coinciding thermal-noise spectra. Regression:
all 53 example verify suites ALL PASS (no compiler/ngspice source changes
in this enhancement).
