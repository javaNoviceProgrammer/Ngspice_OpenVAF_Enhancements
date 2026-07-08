# Enhancement-52 — idt() assert/reset forms

This document describes the change made to **OpenVAF-r** in the `version11/`
directory to fix the **`idt(expr, ic, assert[, tol|nature])` reset forms** —
the E-28 leftover and the last open item of the integrator family.
`hir_lower`-only; no OSDI/ngspice change.

## The defect

Per the LRM, while `assert` is nonzero the integral output is reset to `ic`
and held; integration resumes from `ic` when `assert` returns to zero. The
previous lowering selected between "integrate" (`resist = −expr`,
`react = val`) and "pin" (`resist = val − ic`, `react = ic`) — so at the
reset onset the reactive residual (the integrator's stored charge)
**jumped** from the integrated value to `ic`. The transient integrator's
d/dt term turned that jump into a one-step impulse — the exact failure mode
Enhancement-27 documented for `idtmod`'s state wrap. Externally-driven
resets mostly survived (the impulse settled between measurement points), but
a **self-referential** reset (`idt(1.0, 0.0, V(out) > 1.0)`) fed the impulse
back into its own condition: the probe's 1 V/s ramp rang chaotically, went
negative, and spiked to ~400 V.

## The fix (smooth charge + bounded stiff decay)

- The reactive residual is **always `val`** — the charge never jumps, at
  either the reset onset or the release.
- Reset is a stiff first-order decay: `resist = K·(val − ic)` with
  `K = 1e5` (τ = 10 µs), so the output is driven to `ic` fast but
  continuously.
- A **conditional `bound_step`** (2/K = 20 µs) is emitted only while the
  decay is active (`|val − ic| > 1e-6·(1 + |ic|)`) — keeping the trapezoidal
  method in its deadbeat region so the stiff mode cannot ring — and released
  once settled, so an assert held for seconds simulates at full speed.
  (An unbounded τ = 1 ns decay was tried first: trap's ±1 amplification of
  stiff modes made the oscillator undershoot to −0.25 and stretched its
  period 40%.)
- The DC/IC phase keeps the E-28 behavior: `val` pinned to `ic`
  algebraically, with the charge (`= val = ic`) handing over continuously
  into transient.

## What now works (`idtassert_examples/`, all exact)

| case | result |
|---|---|
| external reset pulse | ramp 0.5→1.5, held at 0.5, resumed to 1.5 |
| op-dependent integrand + reset at the op + tol form | 0.25 held, then 2 V/s |
| self-referential `V(out) > 1` reset | **bounded at exactly 1.0** (was ~400) |
| relaxation oscillator (`idt` + hysteretic cross reset) | peaks 1.0, valleys at `ic`, **period exactly 1 s**, no undershoot |

`verify_idtassert.py`: 9/9 PASS. Regression: all 47 example verify suites ALL
PASS; 28/28 crate tests.

## Notes

- A non-hysteretic self-reset (`assert = output > threshold`) settles at the
  threshold (a sliding equilibrium) rather than oscillating — correct
  continuous dynamics; oscillators need hysteresis, as demonstrated.
- The nature-typed 4th-argument form compiles and behaves as the tol form
  (tolerances remain accepted-but-unused, the project-wide convention).
