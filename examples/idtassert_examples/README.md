# idtassert_examples — idt() assert/reset forms (Enhancement-52)

Demonstrates the **`idt(expr, ic, assert[, tol])` reset forms** — the last
open item of the integrator family after E-27 (`idtmod`) and E-28 (`idt`
initial conditions) — using the committed `openvaf-r` and `ngspice-46`.

## What was broken

While `assert` is nonzero the integral must be reset to `ic` and held;
integration resumes from `ic` on release. The old formulation pinned the
output algebraically while the integrator's stored charge **jumped** at the
reset onset — the transient d/dt term saw that jump as an impulse (exactly
the E-27 `idtmod` failure mode). Externally-driven resets mostly survived,
but a **self-referential** reset (`idt(1.0, 0.0, V(out) > 1.0)`) rang
chaotically and ran away to ~400 V on a 1 V/s ramp.

E-52 keeps the charge **smooth** (the reactive residual is the output,
always) and implements reset as a stiff first-order decay to `ic`
(τ = 10 µs), with a **conditional `bound_step`** holding the transient
integrator inside the decay's stability region (trapezoidal deadbeat) —
released once the output settles at `ic`, so long holds simulate at full
speed. DC/IC-phase pinning and the E-28 charge handoff are preserved.

## Run

```
python3 verify_idtassert.py
```

Checks (ALL PASS, exact): the externally-reset integrator ramps 0.5→1.5,
holds at 0.5, resumes to 1.5; an op-dependent integrand with the reset active
at the operating point (and the tol form) holds 0.25 then ramps at 2 V/s; the
self-referential reset stays bounded at exactly the threshold (was ~400); and
the payoff — a **relaxation oscillator** built from `idt` + hysteretic
cross-event reset: peaks 1.0, valleys at `ic` with no undershoot, period
exactly 1 s.
