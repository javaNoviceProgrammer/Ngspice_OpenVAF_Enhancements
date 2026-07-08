# Enhancement-66 — Monte Carlo with OSDI devices: validation deliverable

This document records the Enhancement-66 probe of **Monte Carlo
(statistical) simulation over OSDI parameters** — the remaining workflow
gap after parameter sweeps (E-62) and `alter`. **No defects were found —
ngspice's statistical machinery fully reaches OSDI parameters** — so, like
Enhancements 57 and 60, the deliverable is the validation itself: a probe
battery, a pinned example suite with distribution plots, and this
write-up. No compiler or ngspice source changes.

## Both standard MC idioms work

1. **The `reset` idiom.** `.param rr = agauss(1k, 100, 3)` feeding a
   `.model` card (`r={rr}`) *or* an instance line (`N1 a 0 mm r={rr}`,
   requires the `(* type="instance" *)` param kind from E-62): each
   `reset` re-throws the dice and re-runs the OSDI model/instance setup.
   Verified over 200-run ensembles: parameter readback (`@n1[r]`) gives
   mean ≈ 1 kΩ and σ ≈ 33.3 Ω (= avar/sig), all draws within ±5σ, and the
   output-current spread matches σ_I ≈ σ_R/R².
2. **The `alter` loop.** Control-language random vectors (`sgauss(0)`
   standard normal, `sunif(0)` uniform on **[−1, 1]** — not [0, 1]) with
   `alter @n1[r] = value` per run: no netlist re-parse, and `setseed N`
   makes the entire run sequence **bit-reproducible** (two seeded
   200-run passes produce identical statistics to the last digit).

Also verified: `aunif(nom, avar)` bounds respected with a uniform-like
spread (σ ≈ 2·avar/√12); single-draw seeded `reset` reproducibility; and a
**nonlinear MC** — an OSDI diode with `is_={agauss(1e-15, 2e-16, 3)}` whose
op-point spread matches the analytic sensitivity σ_V ≈ v_t·σ_Is/Is
(1.54 mV measured vs 1.73 mV analytic, N = 100).

## The documented gotcha

Every textual occurrence of a random-valued `{param}` **draws
independently**: an OSDI device and a built-in resistor written with the
same `{rr}` differ run by run (pinned: max |ΔI| = 9.2e-5 ≠ 0 over 25
runs). Matched/correlated devices therefore need the `alter` idiom, where
one control-language value is explicitly assigned to each instance.
(This is stock `.param` semantics, not an OSDI behavior — but it is
exactly the kind of trap a mismatch analysis falls into, so the suite
pins it.)

## Examples (`montecarlo_examples/`, 10 checks, ALL PASS)

`verify_mc.py`: [1] reset-idiom MC on a model-card param (mean and σ vs
analytic); [2] instance-line param with `@n1[r]` readback (±5σ bounds);
[3] seeded `alter`+`sgauss` loop — σ analytic + two passes bit-identical;
[4] `aunif` bounds and spread; [5] seeded single-draw reproducibility;
[6] the independent-draws gotcha; [7] nonlinear diode MC vs the analytic
sensitivity.

`plot_mc.py` renders `plots/mc_distributions.png`: 500-run gaussian and
uniform MC histograms sitting on the **analytic transformed densities**
of I = 1V/R (including the 1/i² tilt of the uniform case).

## Notes

- `wrdata` is unusable for control-created vectors: it pairs each vector
  with the *current plot's* scale, which after the last `op` has length
  1 — a 500-long MC vector writes as one row. The plot script parses
  `print <vec>`'s indexed table instead.
- Regression: **no compiler/ngspice source changes in this enhancement**;
  the Enhancement-65 full regression (61 suites, crate tests, 92/92
  corpus) stands, plus this suite's 10 checks.
