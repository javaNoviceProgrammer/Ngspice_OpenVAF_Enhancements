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

Checks (17, ALL PASS, exact; 9 before [E-678](../../enhancements_doc/Enhancement-678.md)): the externally-reset integrator ramps 0.5→1.5,
holds at 0.5, resumes to 1.5; an op-dependent integrand with the reset active
at the operating point (and the tol form) holds 0.25 then ramps at 2 V/s; the
self-referential reset stays bounded at exactly the threshold (was ~400); and
the payoff — a **relaxation oscillator** built from `idt` + hysteretic
cross-event reset: peaks 1.0, valleys at `ic` with no undershoot, period
exactly 1 s; and, since E-678, the same reset at the microsecond scale
(`idt(1e6, 0.5, V(rst) > 0.5)` under a 2 µs pulse, `.tran 0.1u 5u`) holds
0.5 throughout and resumes from it, under trapezoidal and Gear alike --
the reset's time constant follows the transient's print step instead of
a fixed 10 µs, and its gain is capped at 2/h so the onset step cannot flip
the trapezoidal rule.

## Enhancement-722: an idt asserted on analysis("static") in .ac and .noise

Since [E-722](../../enhancements_doc/Enhancement-722.md) (correctness campaign 2,
F1 of 2026-09-25) an integrator asserted on `analysis("static")` -- LRM 4.5.5's
own idiom for one pinned at the operating point -- is an integrator in `.ac`
and `.noise`. ngspice's small-signal linearisation pass, the one evaluation
whose Jacobians the whole sweep uses, ran with the operating point's flags
(`static` 1) where LRM Table 4-22's AC and NOISE columns have `static` 0, so
the compiler's select between `ic` and the integrator state took `ic`: a 1 nF
integrator behind 1 kΩ read 1/R = 1 mA in `.ac` where 6.283e-6 A was due, its
dual (`I <+ g·idt(V)`) read 0 where 1.59e-7 A was due, and a topology switched
on `"static"` linearised its static branch, a short. The same modules asserted
on `"ic"` were right all along, and every transient matched. `idtac.va` holds
the four modules; section 5's six checks read the `.ac` magnitude and phase,
the `.noise` output spectrum against the `"ic"` form, and the transient.
