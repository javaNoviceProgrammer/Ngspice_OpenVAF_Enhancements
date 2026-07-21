# Enhancement-260 — LTE step-controller accuracy proof (stiff circuit)

An extension of Enhancement-259 (the transient integration accuracy proof). E-259
verified the integration *methods* with a **fixed** step (freezing the LTE
controller to isolate the truncation order). This adds the complementary property:
that the **adaptive local-truncation-error (LTE) step controller** actually
*delivers* the accuracy the user requests via `reltol` — on a stiff circuit, the
hard case.

## What it audits

On a stiff circuit the LTE controller has a real job: with a fast and a slow mode
1000× apart, it must take tiny steps to resolve the fast decay, then coarsen for
the slow tail. The question is whether the delivered accuracy actually *tracks*
`reltol`, or whether the LTE estimate mis-sizes the steps (a too-optimistic
estimate would take steps that are too large and silently deliver less accuracy
than promised).

Test: two independent decays `v_f=exp(-t/1µs)`, `v_s=exp(-t/1ms)` (stiffness ratio
1000), integrated with one adaptive step. Swept over `reltol`, the delivered error
vs the closed form must shrink monotonically — measured:

```
reltol     err(fast)   internal steps
1e-3       9.0e-3      1032
1e-5       6.0e-4      1089
1e-7       3.7e-5      1284
1e-9       2.0e-6      1884   (no plateau)
```

The error scales as ≈ `reltol^0.6` — the theoretical global-error rate for a
2nd-order method under LTE step control (`reltol` is a *local* per-step tolerance;
the step size adapts as `reltol^(1/3)`, giving global error `~reltol^(2/3)`). The
internal step count rises with tighter `reltol`, and the error never plateaus.

Separately confirmed while building this (not asserted in the verify): the
controller handles **extreme stiffness** (ratio 1e6, `τ=1ns`/`1ms`) with the error
still tracking `reltol`, and **re-excited** fast modes (a 1 MHz square wave)
by refining heavily at each edge (step count jumps ~6× at tight `reltol`).

## Verification

`examples/integaccuracy_examples/verify_integaccuracy.py` gains check **[6]**: on
the stiff circuit the delivered error at `reltol = 1e-3 / 1e-5 / 1e-7` is strictly
decreasing and improves ≥10× (measured ~247×) — both solvers. Checks [1]–[5] (the
E-259 method/order/energy proofs) are unchanged.

## Scope

Verification only — no ngspice source change. Completes the transient-engine proof:
E-259 covers the integration *methods* (order, energy, breakpoints, nonlinear
charge) and E-260 covers the adaptive *step controller* (delivered accuracy vs
`reltol` on a stiff circuit). Full regression passes on both solvers.
