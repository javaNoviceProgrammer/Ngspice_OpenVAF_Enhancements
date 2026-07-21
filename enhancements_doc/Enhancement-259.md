# Enhancement-259 — transient integration accuracy proof

An oracle-based correctness proof for ngspice's **transient integration engine**,
in the same mold as the Harmonic-Balance exactness proof (E-251) and the `.disto`
machine-exact proof (E-255). It codifies, as a permanent both-solver regression
guard, that the integrator has the correct mathematical *properties* — order of
accuracy, energy behavior, breakpoint handling, and nonlinear-charge order — proven
against closed-form analytics and Richardson self-convergence.

## Motivation

The transient integrator is one of the most critical core subsystems, but there
was no oracle-based regression test for its *order of accuracy* or *energy
signature* — existing examples check specific waveforms, not the integrator's
defining properties. A regression that corrupted an integration coefficient
(`NIcomCof`), broke a method's order, or made the trapezoidal-ringing BE-switch fire
spuriously could pass every waveform test while silently degrading every transient.

## What it proves (both solvers — the integrator is solver-independent)

| # | property | oracle | result |
|---|---|---|---|
| 1 | order of accuracy | RC decay `exp(-t/RC)`, error `~dt^p` | TRAP p≈1.94, Gear2 p≈1.93, BE p≈0.94 |
| 2 | energy signature | LC `cos(ωt)`, 30 periods | TRAP amplitude ratio 0.9999 (conserved); BE 0.057 (dissipative) |
| 3 | breakpoints | `PULSE` edge into RC | max err 6e-7, pre-edge pinned at 0 |
| 4 | damped oscillation | RLC `exp(-αt)(cos+…sin)` | max err 4.3e-6, correct `ω_d`/envelope |
| 5 | nonlinear charge | diode+`CJO` rectifier, Richardson | TRAP order p=2.00 |

The order test freezes the LTE step controller (`trtol=1e11`) so the steps are
uniform and the measured convergence is purely the method's truncation order. The
energy test is the key qualitative discriminator: a correct trapezoidal rule is
marginally stable on an LC (no numerical damping), while BDF/Gear methods are
dissipative — and a spuriously-firing ringing damp would show as TRAP amplitude
decay, which it does not (0.9999 over 30 periods).

Separately confirmed while building this (not asserted in the verify, as it needs
`.options dynorder` + `set ngdebug`): the higher-order Gear (BDF) path actually
engages — with adaptive stepping `maxord=6` reaches integration order 6 and rejects
~10× fewer steps than order 2 (14 vs 143 on the RLC), so the high-order BDF
coefficients are functional, not a no-op.

## Verification

`examples/integaccuracy_examples/verify_integaccuracy.py` (both solvers). All five
checks pass; Sparse and KLU give identical results (the integrator is
solver-independent). Scratch decks are `_*.cir` (gitignored).

## Scope

Verification only — no ngspice source change. The audit that produced it also swept
the whole transient path (methods TRAP/Gear2-6/BE, orders, breakpoints, RLC,
adaptive LTE, nonlinear charge) and found it correct; this enhancement makes the
proof a permanent guard.
