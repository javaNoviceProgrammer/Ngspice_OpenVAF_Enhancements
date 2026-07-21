# Transient integration accuracy proof (Enhancement-259)

An oracle-based correctness proof for ngspice's **transient integration engine**,
in the same mold as the Harmonic-Balance exactness proof (E-251) and the `.disto`
machine-exact proof (E-255). Instead of checking one waveform against one
reference, it proves the integrator's mathematical *properties* against closed-form
analytics and self-convergence — the kind of thing a wrong integration coefficient
(`NIcomCof`), a broken method order, or a spuriously-firing trapezoidal-ringing
damp would violate.

## What it proves (both solvers — the integrator is solver-independent)

- **[1] Order of accuracy.** On an RC decay `v(t)=exp(-t/RC)`, the global error vs
  the closed form scales as `dt^p` with the theoretical order: **TRAP → p≈2**,
  **Gear2 → p≈2**, **Backward-Euler (Gear order 1) → p≈1**.
- **[2] Energy signature.** On an LC oscillator `v(t)=cos(ωt)` over 30 periods,
  **TRAP preserves the amplitude** (marginally stable / energy-conserving — and the
  trapezoidal-ringing BE-switch does *not* fire spuriously), while **Backward-Euler
  is dissipative** (amplitude decays strongly). This qualitative split is the
  fingerprint of a correct trapezoidal vs BDF implementation.
- **[3] Breakpoints.** A `PULSE` edge into an RC matches the piecewise-analytic
  charge response, with the pre-edge value pinned exactly at 0.
- **[4] RLC damped sinusoid.** The transient matches the closed form
  `exp(-αt)(cos ω_d t + (α/ω_d) sin ω_d t)` — correct damped frequency *and*
  envelope.
- **[5] Nonlinear charge.** A diode + junction-capacitance (`CJO`) rectifier
  converges under Richardson (TRAP, `dt → dt/2`) at order ≈2 — so the nonlinear
  device charge integration is 2nd order too, not just the linear elements.

Separately confirmed while building this (not asserted here, as it needs the
`dynorder` option and `set ngdebug`): higher-order Gear actually engages —
`maxord=6` reaches integration order 6 and rejects ~10× fewer steps than order 2.

## Verification

`verify_integaccuracy.py` (both solvers). Scratch decks are `_*.cir` (gitignored).

## Scope

Verification only — no ngspice source change. A permanent regression guard that
would catch any future change that broke an integration coefficient, method order,
or the energy behavior of the transient engine.
