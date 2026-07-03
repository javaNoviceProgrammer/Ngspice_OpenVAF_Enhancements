# Enhancement-28 — `idt(...)` initial-condition fix (version11)

This document describes the change made to **OpenVAF-r** in the `version11/`
directory to fix the **initial condition of `idt(expr, ic[, ...])`** in transient
analysis. `idt` integrated correctly, and its IC was honoured at the DC operating
point, but the IC was **silently lost in transient**.

## The bug

`idt(expr, ic)` is an ideal integrator: its value is `ic` at t=0 and then
integrates `expr`. Observed behaviour:

- `.op` of `idt(1, 3)` returned `3` — the IC **was** applied at DC;
- but a transient of `idt(1, 3)` started at `3` for the very first sample and then
  **immediately dropped to 0** and integrated from there, giving `v = t` instead of
  `v = 3 + t`;
- `idt(0, 7)` (zero integrand — should hold at 7) **drifted from 7 to 0**.

The LRM says the IC is *"used as the starting value for transient analysis,"* so
this is a genuine bug.

### Root cause

`idt` lowers to an implicit DAE equation `resist + d/dt(react) = 0` whose unknown
is `val` and whose reactive residual `react` is the integrator's stored charge
`Q`. `EnableIntegration` is false during the DC operating point and true during
transient. The old lowering used, for the IC (integration-disabled) phase:

```
[ val - ic, F_ZERO ]      // resist = val - ic  (pins val = ic);  react = 0
```

So at the DC operating point `val = ic` but the **stored charge `Q = 0`**. When
transient integration turned on (`react = val`), the integrator's history had
`Q = 0`, so it restarted the integral from 0 — the IC was applied at DC but never
carried into transient.

## The fix

Store the charge as `ic` during the IC/DC phase:

```
[ val - ic, ic ]          // resist = val - ic;  react (charge) = ic
```

Now the DC operating point has `val = ic` **and** `Q = ic`, so when transient
integration turns on it continues from `Q = ic` (the state is continuous at the
DC→transient boundary because `val = ic` there). One-value change in
`hir_lower/src/expr.rs` (`lower_integral`); no OSDI ABI change, no ngspice change.

## Verification

`idtic_examples/verify_idtic.py` (`ALL PASS`), an ideal integrator `v = ic +
rate*t`:

- the DC operating point equals `ic`;
- the transient ramp starts from `ic`: `idt(1, 3)` gives `3 + t` (~1e-4) — it used
  to give `t`;
- with `rate = 0` the integrator holds at `ic`: `idt(0, 7)` stays at 7 (was
  drifting to 0).

`idtmod` (Enhancement-27) still works, and every prior example folder still passes.

## Known limitations

- This fixes the DC→transient IC carry for `idt(expr, ic)` (and the same IC phase in
  `idtmod`). The mid-transient **`assert` reset** form `idt(expr, ic, assert)` — a
  runtime reset of the integrator to `ic` whenever `assert != 0` — is a separate,
  harder problem: it forces a discontinuous state jump the transient integrator
  cannot follow smoothly (like the raw `idtmod` wrap), and remains unaddressed.
- `idt(expr)` with no IC still has an unconstrained DC operating point (nothing pins
  the integration constant), unchanged.
