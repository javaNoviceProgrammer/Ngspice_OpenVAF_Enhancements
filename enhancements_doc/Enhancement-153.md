# Enhancement-153 — Levenberg-Marquardt trust-region Newton (`.option trustregion`)

The [gap analysis](../docs/internals/ngspice_internals/ngspice_gaps.md) listed
"Damped / trust-region (globalized) Newton" as ⚠️. ngspice already had a
principled *damped* Newton — the [Enhancement-111](Enhancement-111.md) Armijo line
search — plus per-device junction limiting, node damping, and the gmin/source-
stepping homotopy. What it did not have was a *trust-region* method: one that
damps the **Jacobian** (re-aiming the step direction), not just the step length.
This enhancement adds it.

## What it does

`.option trustregion` (off by default) monitors the true KCL residual
`‖F(x)‖ = ‖G·x − b‖` (the Enhancement-111 merit). If a Newton step **increases**
the residual, the step is **rejected**: a dimensionless damping `lambda` is grown
and the step is retried, with

```
x_{k+1} = x_k − (J + mu·I)^-1 F(x_k),   mu = lambda·‖diag(J)‖
```

The `mu·I` term is added to the Jacobian diagonal at factor time, and the matching
`mu·x_k` is added to the RHS (the same coupling Enhancement-127's pseudo-transient
uses, with `x_prev = x_k`) so the solve produces the *exact* damped step. The
`‖diag(J)‖` scaling makes `lambda` dimensionless (Marquardt), so it is
scale-invariant. As `mu` grows the step rotates from the Newton direction toward
steepest descent — regularizing an ill-conditioned or near-singular Jacobian,
which a line search (shortening a fixed, possibly-bad direction) cannot. When a
step succeeds, `lambda` relaxes back toward 0.

**It is result-neutral.** The fixed point of the damped iteration is `F = 0` for
*any* `mu`, so it converges to the same operating point as plain Newton; and a
convergence guard forbids declaring convergence while `lambda > 0`, so the
accepted point is always an undamped Newton step. Verified **bit-identical** to
plain Newton on every circuit tested, under both linear solvers.

## Honest scope — why it is usually inert

An important, measured finding: on ordinary circuits the trust-region **never
activates** (`lambda` stays 0). The reason is architectural — **ngspice globalizes
Newton at the *device* level, not the *solver* level.** Its per-device junction
limiting (`limexp` / `pnjlim` / `fetlim`, across 30 device families) damps the
controlling voltages *before* the residual is computed, so a residual-increasing
overshoot never reaches the solver-level merit test — there is nothing to reject.
On the pathological cases that defeat limiting (pure behavioral sources, steep
exponentials) Newton converges *monotonically* (tiny steps, no overshoot), and the
homotopy cascade + node damping catch the remainder. Instrumenting the step-
rejection counter across diode strings, behavioral exponentials, cubics, and
negative-resistance oscillators found **zero rejections**.

So `.option trustregion` is a correct, safe, *solver-level* regularization that
completes the damped/trust-region-Newton capability, but on typical circuits the
device-level machinery already does its job and the option stays inert. This is
itself the explanation for why the gap was ⚠️ and hard to move: the capability was
present, just implemented as device limiting + homotopy + line search rather than
as a textbook trust-region.

## Implementation notes

- **`maths/ni/niiter.c`** — in the Newton loop: (1) the E-111 merit block is
  reused (gated on `linesearch || trustregion`); (2) when `lambda > 0`, `mu` is
  added to `trGmin` (the effective diagonal-gmin passed to `SMPreorder`/`SMPluFac`)
  and `mu·x_k` to the RHS; (3) a post-solve **accept/reject** block re-loads at the
  trial point, computes `‖F(x_new)‖`, and either accepts (relax `lambda`) or
  rejects (restore `x_k`, grow `lambda`, force another iteration) — reusing the
  E-111 state-save/limiting-reset machinery; (4) a convergence guard blocks
  convergence while `lambda > 0`. Line search and trust-region are mutually
  exclusive.
- **`maths/KLU/klusmp.c` + `smpdefs.h`** — a new `SMPdiagNorm()` returns
  `max|diag(J)|` (for both the KLU and Sparse matrices) as the Marquardt scale.
- **Option plumbing** mirrors `linesearch`: `OPT_TRUSTREGION` (optdefs.h),
  `IF_FLAG` table entry + handler (cktsopt.c), `TSKtrustregion`/`CKTtrustregion`
  fields + `CKTtrLambda` (tskdefs.h/cktdefs.h), defaults + copy (cktntask.c),
  task→ckt (cktdojob.c).
- Solver-independent (lives in the shared Newton loop).

## Verification

`examples/trustregion_examples/verify_trustregion.py`, under **both** solvers:

- **result-neutrality** — `.option trustregion` == plain Newton **bit-for-bit** on
  a diode circuit, a BJT amplifier, and a resistor divider;
- **correctness** — the solution matches the analytic value;
- **transient neutrality** — a diode-RC transient is unchanged (the trust-region
  touches only the DC/tran operating point).

`trustregion_demo.cir` solves a diode circuit with plain and trust-region Newton —
the same operating point to 12 digits.

## Scope and follow-ups

A correct, result-neutral, scale-invariant Levenberg-Marquardt trust-region Newton
is now available, completing the damped/trust-region-Newton row. Because the
device-level machinery pre-empts it on typical circuits, the more impactful
convergence follow-up is **auto-triggering** the existing aids (reaching for the
line search / gmin-stepping automatically when Newton stalls, without the user
setting an option) rather than a further solver-level algorithm.
