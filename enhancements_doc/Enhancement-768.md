# Enhancement-768: `optimize -method tr` — a derivative-free trust region on a quadratic model, the local method the polish and the surrogate's hand-off were missing: one evaluation per step, a Hessian learned from 2n + 1 points, the knob bounds inside the subproblem; two to seven times fewer evaluations than Nelder-Mead, and no simplex to go flat against a wall

**Scope:** section 4 of the proposal [more optimizers for `optimize`](../docs/proposals/2026-09-29_optimize-more-methods.md)
(2026-09-29). ngspice only: `frontend/com_optimize.c` (`trust_region()` with `tr_update()`,
the least-change quadratic interpolation; `tr_box_qp()`, the bound-constrained subproblem;
`tr_axis_set()`; `-method tr`, aliases `trust`, `trustregion`, `quad`, `quadratic`; the
polish of E-764 and the hand-off of E-765 run it for a scalar objective, where they ran
Nelder-Mead; Levenberg-Marquardt stays the finisher for a `-target` fit and Nelder-Mead
the `-minimize` default).

**Suites:** `optmethods` 97 of 97 (74 of 97 on the E-766 binary); `optimize` 73 of
73 (its bare `-method` message names `tr`); `psoopt`, `deopt`, `saopt`, `pareto`,
`dcenter`, `reuseloops`, `loopguard`, `opt100`, `optknown`, `optname`, `autobusopt`,
`autoopts`, `paramfastsweep`, `mcfastpath`, `agestate` and `mcpolicy` unchanged; the full
sweep 535 of 535.

## Why a second local method

Everything added since E-764 ends in a local finish, and for a scalar objective that was
Nelder-Mead. It was the weak link three times over. It converges linearly: taking the
bowl's cost from 1e-7 to 1e-13 cost the surrogate's hand-off about 75 evaluations, more
than the surrogate spent finding the basin. It counts iterations of two evaluations, so a
hand-off's budget was overrun or ended `NOT converged` short of the optimum. And clamped
against a knob's bound its simplex goes flat — every vertex the same clamped value in one
coordinate — and stops: E-765's hand-off on the ellipsoid ended in a box corner at 0.18,
and E-766 had to rebuild the simplex under a constrained solve.

## What changed

**The method.** `trust_region()` keeps 2n + 1 points, interpolates them with a quadratic
model, and minimises the model inside a box of radius Δ around the best point
intersected with the knob bounds.

- *The model* is updated by the least-change rule: of all quadratics that interpolate
  the points, the one whose Hessian differs least (Frobenius norm) from the previous
  one, from the KKT system `[A X; Xᵀ 0][λ; Δc, Δg] = [r; 0]` with `A_jl = (y_jᵀy_l)²/2`,
  solved directly in coordinates scaled by the radius (at most 386 unknowns; a dense
  solve is milliseconds). From a zero Hessian this is the minimum-norm model; as points
  move, curvature accumulates. A solve that is singular or does not interpolate rebuilds
  the axis set at the current radius.
- *The subproblem* is a bound-constrained quadratic program: the trust region is a box,
  the knob bounds are a box, their intersection is a box. `tr_box_qp()` takes a Newton
  step on the free coordinates with the bound ones held, growing the active set one hit
  at a time, then polishes by exact coordinate minimisation and cross-checks against
  coordinate minimisation from zero. Nothing is clamped afterwards: a step runs along a
  wall instead of being projected onto it.
- *The iteration* costs one evaluation: the trial point. The ratio of the actual to the
  predicted decrease accepts it (≥ 0.1), doubles the radius when the model was good and
  the step reached it, shrinks it when the model was poor; the trial point replaces the
  point farthest from the centre, so the set follows the search.
- *Convergence.* When the model expects less than `-tol` of decrease, points farther
  than two radii are brought in one at a time (a geometry step: the model is trusted
  only where its points are). With none left the search is `converged` if the last trial
  step delivered what the model predicted (ratio within a quarter of 1: the model has
  just proven itself); otherwise the radius drops tenfold and the test repeats, down to
  a radius of `-tol`. Rejected steps that shrink the radius to `-tol` end it as well,
  which is how a noisy objective stops.
- *Failures.* A failed evaluation is not interpolated: the step is refused and the
  radius halved. A start that does not solve looks at its axis points for one that
  does; when none does the epilogue reads NO SOLUTION.

The first radius is 0.1 of the box (0.05 for a polish and 0.02 for the surrogate's
hand-off, the values the simplex edge had). `-verbose` prints one line per iteration:
the cost, the radius and the ratio, or `model minimum` / `geometry`.

**Measured** on objectives posed inside ngspice, evaluations to `converged`:

| problem | Nelder-Mead | trust region |
|---|---|---|
| a bowl in two knobs | 3.6e-13 after 103 | 0 after **9** |
| a rotated ellipsoid, condition 1e6 | 5e-13 after 134 | 2.4e-11 after **33** |
| Rosenbrock in four knobs | 7.6e-13 after 377 | 8.1e-10 after **132** |
| a coupled quadratic in ten knobs | 0.0824983 after 996 | 0.0824981 after **146** |
| an optimum on a wall | v2 = 0.700093 after 62 | v2 = 0.7 after **10**, v1 exactly 0 |
| an optimum in a corner | after 54 | after **36** |
| hunt O1's one-knob deck | 2.1e-14 after 47 | 4.2e-14 after **13** |
| the divider fit as a scalar | 2.4e-13 after 35 | 7.9e-15 after **12** |

**What the polish gained.** E-764's `-polish` and E-765's hand-off now run the trust
region for a scalar objective (the lines read `polish -- Trust-Region from the best
point`):

| run | with Nelder-Mead (E-764 to E-766) | with the trust region |
|---|---|---|
| hunt O1's swarm, `-polish` | 0.036 → 1.3e-12 in 38 evaluations | → 1.7e-14 in **11** |
| the surrogate on the bowl, budget 60 | converged in 91 in all | converged in **26** |
| the same, budget 30 | `NOT converged` at 7e-7 | converged in 26 |
| the surrogate on the ellipsoid | stuck in a box corner at 0.18 | 4.8e-14 in 55 |
| the constrained divider, inner method | 179 evaluations, R1 = 1108.5 | 107, R1 = 1111.11, the multiplier 1e-4 exactly |

**What did not change.** Nelder-Mead is still the `-minimize` default and runs byte for
byte as before, with E-766's rebuild under a constrained solve; Levenberg-Marquardt is
still the default and the finisher for a `-target` fit. The method lists in the usage
line and the messages name `tr`; `-polish` under it is a NOTE and ignored, as under the
other local methods.

## Checks

`examples/optmethods_examples/verify_optmethods.py` sections [28] to [33], 16 checks:
[28] the bowl below 1e-12 in at most 15 evaluations, a third or less of Nelder-Mead's,
the banner naming the method; [29] the ellipsoid below 1e-9 within 60, Rosenbrock below
1e-7 within 200, the ten-knob quadratic at Nelder-Mead's value in a third of its
evaluations; [30] an optimum on a wall with that knob exactly on the bound, an optimum in
a corner; [31] O1's polish in at most 20 evaluations and the surrogate's hand-off on the
ellipsoid converged below 1e-9; [32] the constrained divider at R1 = 1111.1 with the
multiplier within 2 %; [33] `-maxiter 1`, the alias and the `-polish` NOTE, one
`-verbose` line per iteration, a refused start whose axis point solves and one where
nothing does, the E-762 variables. Eight checks of the earlier sections now expect the
trust region in the polish lines and `tr` in the method lists, and the budget check of
section [13] uses a one-iteration remainder, since the old two-thirds-of-a-budget case
now converges.

## Limits

- A quadratic model wants a smooth objective. At an objective's noise floor the ratio
  turns random, the radius collapses and the search stops there as `converged`; a stepped
  objective is outside its design (it happened to solve a coarse regular staircase in 9
  evaluations where the simplex stalled, and that should not be relied on). Pattern
  search, the proposal's section 5, is the method for those.
- The first model costs 2n + 1 evaluations before the first step, and a polish's or a
  hand-off's iteration cap does not count them: a remainder of one iteration spends six
  evaluations on two knobs and reads `NOT converged` with the optimum in hand.
- Convergence on a just-proven model stops at the current radius, so the last digits
  follow `-tol` in cost rather than the simplex's shrink to the last bit: 2.4e-11 on the
  ellipsoid and 8e-10 on Rosenbrock where the simplex reached 1e-13, at a quarter to a
  third of the evaluations.
- A start with no solving axis point still reads NO SOLUTION (the hunt's F6 for the
  local methods).
- Nelder-Mead remains the `-minimize` default; changing it is a separate decision for a
  suite-wide look.
