# idtic_examples — `idt(...)` initial-condition fix (Enhancement-28)

Demonstrates the **`idt(expr, ic)`** initial condition working in **transient**
analysis, using **version11's own** `openvaf-r` and `ngspice-46`.

## What was broken

`idt(expr, ic)` is an ideal integrator whose value is `ic` at t=0 and then
integrates `expr`. The initial condition was applied at the **DC operating point**
(`.op` returned `ic`) but was silently **lost in transient**: the integrator
restarted from 0, so

- `idt(rate, ic)` gave `rate*t` instead of `ic + rate*t`, and
- `idt(0, ic)` drifted from `ic` down to 0.

The cause: during the IC / DC phase the integrator's **reactive residual (stored
charge)** was zeroed while the resistive term pinned `val = ic`. So the charge
saved at the DC operating point was 0, and when transient integration turned on it
continued from 0 charge — losing the IC.

## The fix

Store the charge as `ic` (not zero) during the IC/DC phase, so the transient
integrator continues from `ic`. One-value change in `hir_lower`'s `lower_integral`;
no OSDI/ngspice change.

## Run

```
python3 verify_idtic.py
```

Expected (`ALL PASS`):

- the DC operating point equals `ic` (this already worked);
- the transient ramp starts from `ic`: `idt(1, 3)` gives `3 + t` (used to give `t`);
- with `rate=0` the integrator **holds** at `ic`: `idt(0, 7)` stays at 7 (used to
  drift to 0).

## Notes / limitations

- This fixes the DC→transient initial-condition carry. The mid-transient **`assert`
  reset** form `idt(expr, ic, assert)` — which resets the integrator to `ic`
  whenever `assert != 0` — is a separate, harder problem: it forces a discontinuous
  state jump the transient integrator can't follow smoothly (much like the raw
  `idtmod` wrap), and remains unaddressed here.
- `idt(expr)` with **no** IC still has an unconstrained DC operating point (no IC to
  pin the integration constant), as before.
