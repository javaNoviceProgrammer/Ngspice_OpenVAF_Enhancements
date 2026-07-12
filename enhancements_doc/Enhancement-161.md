# Enhancement-161 — Dynamic (AC / RF) compact-model validation

[Enhancement-159](Enhancement-159.md) and [Enhancement-160](Enhancement-160.md)
validated the CMC compact models' **DC** behavior — I-V curves against ngspice's
built-in models. But compact models earn their keep in analog and RF, where the
**dynamic** behavior is what matters, and that flows through a completely different
code path: OSDI's **reactive (charge) Jacobian** stamping and ngspice's `.ac`
analysis. This enhancement validates that path on real production models. It is a
validation/example enhancement — no ngspice/openvaf-r source change.

## BSIM4 C-V — a stringent reactive-stamping check

The gate capacitance `Cgg(Vgs)` is extracted from `.ac` as `Cgg = Im(I_gate)/ω`
and swept over gate bias:

![C-V and fT](../examples/dynmodels_examples/dynmodels_ac.png)

It rises from a small subthreshold value (~40 fF, overlap + fringe) to the oxide
capacitance in inversion (~129 fF) — the textbook MOSFET C-V curve — and the
OSDI-compiled BSIM4 matches ngspice's **built-in** BSIM4 to **< 1 %** at every
bias (Panel A, markers on the line). Because the capacitance is dominated by the
version-independent oxide term, this is an even tighter check of the reactive
stamping than the ~2 % DC I-V match in E-159.

## Cutoff frequency fT — the AC current-gain roll-off

`fT` is where the AC current gain `|h21| = |I_out/I_in|` falls to 1 — the single
most important RF figure of merit. Panel B shows the `-20 dB/decade` roll-off and
the `|h21|=1` crossing for two device classes:

- **BSIM4** (MOSFET) — `fT ≈ 3.5 GHz`; the OSDI model matches the built-in to ~1 %.
- **HICUML2** (SiGe HBT) — ngspice has no built-in bipolar reference. The *default*
  model has zero transit time (`t0=0`), so its fT is infinite (a flat `|h21|`); a
  realistic dynamic parameter set (`t0=10 ps`, 1 fF junction caps) is supplied, and
  the resulting fT lands right at the transit-time limit `1/(2π·t0) ≈ 15.9 GHz` and
  rises with collector current — exactly what charge-control theory predicts.

## Verification

[`examples/dynmodels_examples/verify_dynmodels.py`](../examples/dynmodels_examples/verify_dynmodels.py),
under **both** the Sparse and KLU solvers (`.ac` is supported by both):

- **[1]** BSIM4 `Cgg(Vgs)` matches built-in BSIM4 to < 2 % across the C-V sweep
  (measured: 0.8 %).
- **[2]** the C-V curve is physical — `Cgg` rises from subthreshold (~40 fF) to
  inversion (~129 fF).
- **[3]** BSIM4 cutoff frequency `fT` matches built-in BSIM4 to < 3 % (measured:
  3.56 vs 3.53 GHz).
- **[4]** HICUML2 `fT` sits at the transit-time limit `1/(2π·t0)` and rises with
  collector current (15.1 → 15.6 GHz vs a 15.9 GHz limit).

## Why the results are physically correct

- **C-V shape.** In subthreshold the gate sees only overlap/fringe capacitance; as
  the channel inverts, the gate couples to the channel through the oxide, so `Cgg`
  climbs toward `Cox·W·L`. Sub-percent agreement with the built-in model confirms
  the OSDI charge model and its reactive Jacobian are stamped correctly.
- **fT.** A single-pole roll-off gives `|h21| ≈ fT/f`, so `|h21|=1` at `f=fT`.
  `fT ≈ gm/(2π·Cgg)` for the MOSFET and `fT ≈ 1/(2π·τ_f)` for the bipolar in the
  transit-time-limited regime — where the measured 15.5 GHz lands for `t0 = 10 ps`.

## Scope and follow-ups

Together with E-159/160 this establishes that openvaf-r + ngspice reproduces both
the static and dynamic behavior of production compact models. Natural follow-ups:
noise (the models' `.noise` / thermal + flicker vs built-in), large-signal RF
(harmonic distortion, the PSS/HB suite on a real model), and a full per-model
dynamic-parameter sweep.
