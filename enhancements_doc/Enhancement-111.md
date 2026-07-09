# Enhancement-111 — globalized (damped) Newton via an Armijo line search

ngspice solves each DC operating point with Newton's method, which converges only
*locally*: from a poor starting point the full Newton step can overshoot and the
iteration stall or diverge. Commercial simulators guard against this with a
**globalized Newton** — a line search that shrinks the step to guarantee progress
on a *merit function*, the residual norm ‖F‖. ngspice had every other convergence
aid (per-device junction limiting, node damping, gmin/source-stepping homotopy)
but **not** a principled residual-based line search, because it had **no way to
compute ‖F‖** mid-solve: its convergence test is purely iterate-based
(`|Δx| < tol`).

This enhancement adds both: the residual merit, and an Armijo backtracking line
search built on it.

```
.option linesearch     ; enable the line search (OFF by default)
```

## The residual merit ngspice lacked

In modified nodal analysis, after `CKTload` builds the Jacobian `G` and the
right-hand side `b` at the point `x`, the Newton (KCL) residual is exactly
`F(x) = G·x − b` — the net current mismatch at every node. It is computed here on
the just-loaded, **unfactored** matrix via ngspice's own sparse matrix-vector
product `SMPmultiply` (which requires an unfactored matrix). This is a genuinely
new, reusable capability: the tolerance-weighted ‖F‖ that a globalized Newton — or
future work like pseudo-transient continuation — needs.

## The line search

When enabled and the iteration is not converging, the full Newton step
`x_k → x_full` is damped by the largest `λ ∈ {1, ½, ¼, …, 1/64}` giving a
sufficient decrease of ‖F‖ (the Armijo condition, `c = 1e-4`). Each trial
**re-loads the devices** at `x_k + λ·d` and re-evaluates ‖F‖. At or near a
solution the full step already reduces ‖F‖, so `λ = 1` is accepted on the first
trial and the run is **result-neutral**; backtracking only engages on genuine
overshoot.

Three subtleties had to be solved to make this correct (the full reasoning is in
the [implementation write-up](../docs/internals/ngspice_internals/)):

- **The residual is only computable after ordering.** `SMPmultiply` reads the
  matrix's external-ordering maps, which are populated by the *first*
  factorization — so the merit is gated to `iterno > 1` (before that it would
  read garbage and crash). The merit is built by `SMPmultiply`, ngspice's sparse
  matrix-vector product. Under the default **Sparse 1.3** solver this works
  directly; under **KLU** (`.option klu`) it originally segfaulted, fixed in
  [Enhancement-112](Enhancement-112.md) — the line search now runs identically
  under both linear solvers (merit sequence numerically identical between them).
- **SPICE device limiting is stateful.** Junction-voltage limiting is referenced
  to the previous iterate stored in `CKTstate0`; naive trial re-loads drift that
  reference and destroy the iteration. The trial loads are made **state-neutral**
  by restoring `CKTstate0` to the `x_k` state (`OldCKTstate0`) before every trial
  and after the search, so the trials leave no trace but the chosen step.
- **DC is a multi-phase state machine.** The operating point runs
  `MODEINITJCT → MODEINITFIX → MODEINITFLOAT`, and ‖F‖ is only a consistent
  function of `x` in the final `MODEINITFLOAT` Newton phase — so the line search
  is gated to that phase.

## Files changed

Additive (117 insertions), confined to the option layer and the Newton iteration;
no device code touched.

| File | What changed |
|---|---|
| `ngspice-46/src/include/ngspice/optdefs.h` | `OPT_LINESEARCH` option code |
| `ngspice-46/src/include/ngspice/tskdefs.h` | `TSKlinesearch` task flag |
| `ngspice-46/src/include/ngspice/cktdefs.h` | `CKTlinesearch` flag; `CKTlsMerit` (the residual ‖F‖); `CKTlsXk`/`CKTlsD`/`CKTlsBufSz` (line-search scratch) |
| `ngspice-46/src/spicelib/analysis/cktsopt.c` | `OPT_LINESEARCH` setter + `"linesearch"` keyword-table entry |
| `ngspice-46/src/spicelib/analysis/cktdojob.c` | copy `TSKlinesearch → CKTlinesearch` |
| `ngspice-46/src/spicelib/analysis/cktntask.c` | `TSKlinesearch` default (off) in both task paths |
| `ngspice-46/src/spicelib/analysis/cktdest.c` | free `CKTlsXk`/`CKTlsD` |
| `ngspice-46/src/maths/ni/niiter.c` | the residual-merit computation (before factorization) and the Armijo backtracking line search (after the solve), with the state-neutral trial re-loads and the `MODEINITFLOAT` gate |

## Verification

[`examples/linesearch_examples/`](../examples/linesearch_examples/) (9/9): a
battery of nonlinear DC circuits (BJT, BJT+diode, two-diode divider, bistable
latch) run with the option OFF and ON — the option is accepted, each still
converges, and (the load-bearing property) the converged node voltages are
**identical** ON vs OFF.

The **backtracking path itself** (λ<1), which ngspice's robust DC init rarely
triggers, was validated separately with a temporary hook that forces a damped step
on every iteration: at λ = 0.5, 0.25 and even **0.1** the same roots are reached —
BJT 2.442076, two-diode 0.679789 — and the **bistable latch converges to the same
basin** as the full-step run under all damping levels. So both the full-step and
the damped-step paths are verified to reach the correct answer.

Regression: the existing verify suites pass unchanged against the rebuilt ngspice
(the feature is compiled in but off by default).

**Honest scope.** This is safe, principled, result-neutral infrastructure. Its
practical *benefit* — converging circuits that otherwise fail — could not be
demonstrated on constructible small circuits, because ngspice's multi-phase init,
limiting, and homotopy already resolve their difficulty before the `FLOAT`-phase
Newton where the line search acts; backtracking would only bite on large or
pathological circuits. The durable win is the residual-merit machinery and a
correct, verified globalized-Newton implementation to build on.
