# Enhancement-765: `optimize -method bayes` — Bayesian optimization with a Gaussian-process surrogate and expected improvement, the method for the slow deck: it locates the basin in ten to twenty evaluations, hands what is left of the budget to the local method, and reports what the surrogate learned (a predicted cost with its uncertainty, a length scale per knob, and which knob the objective ignores)

**Scope:** section 2 of the proposal [more optimizers for `optimize`](../docs/proposals/2026-09-29_optimize-more-methods.md)
(2026-09-29). ngspice only: `frontend/com_optimize.c` (`bayes_opt()` with `struct gp`, a
Matérn-5/2 kernel with one length scale per knob, a Cholesky factorisation, the marginal
likelihood, expected improvement, a Latin-hypercube design; `nm_callback()`, a simplex on
a callback for the surrogate's own minimisations; `-method bayes`, aliases `bo`,
`bayesian`, `gp`, `surrogate`; `-maxiter` as an evaluation budget and the report's word
for it; the hand-off to E-764's polish with the remaining budget; the surrogate line).

**Suites:** `optmethods` 61 of 61 (6 of 61 on the E-763 binary, which refuses both
new method names); `optimize` 69 of 69 (the bare `-method` message names `bayes`);
`psoopt`, `deopt`, `saopt`, `pareto`, `dcenter`, `reuseloops`, `loopguard`, `opt100`,
`optknown`, `optname`, `optpath`, `autobusopt` and `autoopts` unchanged; the full sweep
535 of 535.

## Why a surrogate

Every method the command had spends an analysis per candidate and remembers nothing of
the shape of what it measured: the simplex keeps n + 1 points, the swarm its bests, CMA-ES
a mean and a covariance. When one evaluation is an operating point that is fine; when it
is a transient of seconds on a compiled model, or a corner sweep of minutes, the number of
evaluations is the whole cost, and the right method spends its own arithmetic to save
them. Measured on the E-764 binary, on objectives posed inside ngspice (source values as
knobs, a behavioural source computing the function):

| problem | Nelder-Mead | particle swarm | Levenberg-Marquardt |
|---|---|---|---|
| the divider fit, R2 in [1, 100k], target v(out) = 0.9 | rms 5e-7 after 35 | — | 2e-9 after 16 |
| a smooth bowl in two knobs, (x − 0.3)² + (y − 0.7)² | 4e-13 after 103 | 2e-9 after 1153 | — |

LM is unbeatable on a smooth one-knob fit from a good start; it needs a residual vector,
a start in the right basin and a box it can difference across (the 2026-09-29 hunt's O2).
For a scalar objective the choice was the simplex or a population.

## What changed

**The surrogate.** A Gaussian process with a Matérn-5/2 kernel and one length scale per
knob in cube units, a signal variance and a noise floor (the hyperparameters, bounded: a
length scale between a twentieth of the box and a hundred boxes, the noise between 1e-8
and 1). The targets are the costs, log-transformed when they are all positive and span
two decades or more — a `-target` sum of squares does near its optimum — and
standardised over the solved points; a failed evaluation is imputed at the worst solved
value plus three standard deviations, so the surrogate learns that region is bad without
a discontinuity. The kernel matrix is N × N for N evaluations, factorised by Cholesky;
the hyperparameters maximise the marginal likelihood through a small simplex in log
space at every evaluation while there are fewer than twenty and every fifth after. At
N ≤ 300 all of it is milliseconds; `-maxiter` above 2000 is capped with a NOTE, since the
matrix holds every evaluation.

**The loop.** An initial design of 2n + 2 Latin-hypercube points, the start point among
them (a design in which nothing solved is redrawn, three times at most, then the
epilogue's NO SOLUTION); then, until the budget is spent, the point that maximises
expected improvement over the surrogate — 400 + 100n Latin-hypercube candidates and
twenty perturbations of the best point, the three best refined by the callback simplex,
a point already evaluated never chosen twice. `-maxiter` is the evaluation budget, and
the report's `stopped at -maxiter (N evaluations)` says so; `-tol` is the smallest
expected improvement worth an evaluation, in standardised units. The interrupt is polled
before every evaluation, since one may take seconds. `-swarmsize` does not apply and says
so; `-verbose` prints one line per evaluation, `(design)` for the first 2n + 2 and the
largest expected improvement after.

**The hand-off.** A Gaussian process locates the basin in ten to twenty evaluations and
cannot resolve a cost that falls by orders of magnitude at the optimum: the spike is
sharper than any length scale, and the surrogate fitted to it either declares itself
done or creeps. So when its criterion is met with budget left — the largest expected
improvement below `-tol`; or below a thousandth of the cost spread twice running once the
design and a few steps are behind; or the best unmoved for 10 + 2n evaluations with
little expected — the rest of the budget goes to the local method through E-764's
polish: Levenberg-Marquardt for a `-target` fit, Nelder-Mead otherwise with a first
simplex edge of 0.02 (the point is close), capped at the iterations that remain, and the
polish's status is the final one. The divider fit at a budget of 25:

```
optimize: Bayesian optimization -- a Gaussian-process surrogate (Matern 5/2, a length scale per knob) and expected improvement, seed 1, a budget of 25 evaluations (4 in the initial design)
optimize: surrogate converged after 10 evaluations (it expects less than a thousandth of the cost spread); the budget's remaining 15 evaluations go to the local method
optimize: surrogate -- predicted cost 0.005434 (0.00525 .. 0.00562, one sigma) at the optimum after 10 evaluations, fitted to the cost; length scales (box widths): r2 0.89
optimize: polish -- Levenberg-Marquardt from the best point (cost 0.00533646), up to 15 iterations (the remaining budget)
optimize: polish converged -- cost 0.00533646 -> 0 in 21 evaluations
optimize: converged, sum-sq residual = 0 (rms 0) after 32 evaluations
    r2 = 9000
```

Seeds 1 to 5 hand off after 8 to 14 evaluations and all end at R2 = 9000, in 24 to 33
evaluations. On the bowl the surrogate's best is below 1e-5 after 19 to 23 evaluations
and the polish converges below 1e-12 in 91 to 97 in all, against the simplex's 103 and
the swarm's 1153. With a budget of 30 the polish runs out of its share at about 1e-6 and
the line reads `stopped at -maxiter (11 iterations) -- NOT converged` with the NOTE: the
budget is honoured and the shortfall said. Under `-starts` no start hands off; the winner
is polished as E-764 has it.

**The surrogate's report.** After the search:

```
optimize: surrogate -- predicted cost 0.000103427 (7.42e-05 .. 0.000144, one sigma) at the optimum after 26 evaluations, fitted to log cost; length scales (box widths): v1 0.05 v2 0.05 v3 100 (no dependence seen)
```

That is the bowl with a third knob the objective does not use: its length scale ran to
the ceiling and is labelled. The same label answers E-762's `unchanged` case with a
diagnosis — a single knob the objective ignores reads `unchanged -- nothing was optimised`
on the line and `v1 100 (no dependence seen)` on this one. The prediction is on the cost
scale (back-transformed when the fit was to log cost), the range one standard deviation of
the latent function.

**What did not change.** The seven other methods, their reports and stop tests are byte
for byte what they were; the polish after a population method keeps its 0.05 simplex; a
deck that does not name `bayes` runs as before. The usage line, the unknown-method
message and the `-polish` NOTE list the new name.

## Checks

`examples/optmethods_examples/verify_optmethods.py` sections [11] to [19], 20 checks:
[11] the divider fit at a budget of 25 — the banner with its design size, the hand-off
line with N ≤ 16 and N + M = 25 and its reason, the LM polish line `up to M iterations
(the remaining budget)`, converged at R2 = 9000 within 40 evaluations, seeds 2 to 5
likewise; [12] the bowl — the surrogate's best below 1e-5 within 25 evaluations, the
budget-60 polish below 1e-10 at (0.3, 0.7) in fewer evaluations than the simplex alone,
the swarm above 500; [13] the budget honoured — at 30 the polish's `stopped at -maxiter
(M iterations)` with M = 30 − N and the NOTE, at 3 a truncated design and `3 evaluations`
in the line with `optimize_status = maxiter`; [14] the surrogate line's shape, the
prediction inside its range, `(no dependence seen)` on exactly the unused knob; [15] the
hunt's F6 start imputed and left with E-438's NOTE a minority, a box refused entirely
ending after three designs (13 evaluations) as NO SOLUTION; [16] the `unchanged` verdict
with the length scale saying why; [17] the `-swarmsize` NOTE and the `bo` alias, two
`-seed 1` runs identical and `-seed 2` different, `-verbose`'s `(design)` and `max EI`
lines one per evaluation; [18] `-starts 1` with `evaluations each` in the banner, two
per-start lines, the winner polished, no per-start hand-off; [19] the E-762 variables
equal to the line.

## Limits

- The surrogate's resolution is a twentieth of the box, by the length-scale floor; the
  digits are the local method's, through the hand-off, and a budget too small to leave
  it room ends `NOT converged` at the surrogate's precision (a budget of 12 on the
  divider: rms 1e-2 after 2 LM iterations).
- The polish's cap is in the local method's iterations, and LM spends n + 1 evaluations
  per iteration, so a run can report a few more evaluations than the budget named.
- A valley at an angle to the axes with a condition number of 1e6 is not a surrogate's
  problem class: on the rotated ellipsoid the search hands off at a box corner and the
  simplex, clamped there, does not leave it. CMA-ES is the method for that box
  ([E-764](Enhancement-764.md)). Rosenbrock in four knobs reaches 4.8 after 66
  evaluations before the hand-off; a population method is the better spend there too.
- `(no dependence seen)` is the surrogate's finding, not a fact: on a function it fits
  poorly a length scale can run to the ceiling on a knob that matters (Rosenbrock's
  third).
- `-maxiter` is capped at 2000 with a NOTE; a larger budget belongs to a population
  method.
