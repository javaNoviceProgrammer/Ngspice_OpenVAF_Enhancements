# linesearch_examples — globalized (damped) Newton line search (Enhancement-111)

A SPICE simulator solves each DC operating point with Newton's method, which is
only *locally* convergent — from a poor point the full Newton step can overshoot
and stall. Commercial simulators guard against this with a **globalized Newton**:
a line search that shrinks the step to guarantee progress on a *merit function*
(the residual norm ‖F‖). Enhancement-111 adds this to ngspice:

```
.option linesearch     ; enable the Armijo backtracking line search (OFF by default)
```

To do it, ngspice first needed a **residual merit it never had**: the KCL current
mismatch `F(x) = G·x − b`, computed from the just-loaded, unfactored Jacobian.
The line search then damps the Newton step by the largest `λ ∈ {1, ½, ¼, …}`
giving a sufficient decrease of ‖F‖ (Armijo), re-loading the devices at each
trial point.

It is **off by default and result-neutral**: enabling it never changes the
converged answer — only the iteration *path* can change, and only on overshoot.
It runs in the final `MODEINITFLOAT` Newton phase (the only phase where ‖F‖ is a
consistent function); ngspice's multi-phase DC init already tames most circuits
before that phase, so the full step is usually accepted and backtracking is rare.

## What's here

- `linesearch_demo.cir` — a BJT + diode network you can run directly
  (`ngspice -b linesearch_demo.cir`); toggling `.option linesearch` gives the
  same operating point either way.
- `verify_linesearch.py` — the checks.

## Verify

```
python3 verify_linesearch.py
```

Runs a battery of nonlinear DC circuits (BJT, BJT+diode, two-diode divider,
bistable latch) with the line search OFF and ON and checks (17/17) that the
option is accepted, each circuit still converges, and — the load-bearing
property — the converged node voltages are **identical** ON vs OFF
(result-neutrality). The battery runs under **both** linear solvers, KLU (the
default) and the legacy Sparse1.3 (`.option sparse`), since the residual merit
is built on the shared `SPmatrix` and must be correct under either. The
correctness of the *backtracking* path itself (λ<1) was validated separately by
forcing damped steps on every iteration and confirming the same roots are reached
down to λ=0.1, including on the bistable latch (same basin); see
[`../../enhancements_doc/Enhancement-111.md`](../../enhancements_doc/Enhancement-111.md)
and the [implementation write-up](../../docs/internals/ngspice_internals/).
linesearch is a simulator-side feature, so no Verilog-A model is involved.
