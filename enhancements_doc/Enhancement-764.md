# Enhancement-764: `optimize -method cmaes`, `-polish` and `-starts` — covariance matrix adaptation as a seventh method (it learns the valley's scale and orientation and ranks a failed evaluation last, so it leaves a start the model refuses and settles inside the box where the swarm clamped at the wall), a local finish for every global method, and multi-start with a per-start report

**Scope:** section 1 of the proposal [more optimizers for `optimize`](../docs/proposals/2026-09-29_optimize-more-methods.md)
(2026-09-29), with its section 6, which shares the restart loop. ngspice only:
`frontend/com_optimize.c` (`cma_es()` with a Gaussian draw on E-194's stream and a cyclic
Jacobi eigensolver; `-method cmaes`, aliases `cma`, `cma-es`, `evolutionstrategy`;
`-polish`; `-starts <k>`; Nelder-Mead's first simplex edge as a field so a polish can
start small; the per-start and polish report lines; `optimize_start`). It closes the
2026-09-29 hunt's O1 (a local polish after every global method) and, for this method, its
O2 (a knob spanning decades) and the F6 class (a start inside a failing region).

**Suites:** a new `optmethods` suite, 41 of 41 (5 of 41 on the E-763 binary, which
refuses the method name and the flags); `optimize` 69 of 69 (one expected message gained
`cmaes`); `psoopt`, `deopt`, `saopt`, `pareto`, `dcenter`, `reuseloops`, `loopguard`,
`opt100`, `optknown`, `optname`, `optpath`, `autobusopt` and `autoopts` unchanged; the
full sweep 535 of 535.

## Why a seventh method

The six methods the command had are one static function each over the unit cube,
calling `opt_eval()` for a cost or the failure penalty. Read as a set they have three
gaps, and the proposal page names them: nothing is sample-efficient, nothing copes with
an ill-conditioned box, and nothing beyond the box is a constraint. This enhancement is
the second gap. Measured on the E-763 binary, with the objective posed inside ngspice (the
knobs are the dc values of sources, a behavioural source computes the function, so an
evaluation is one operating point):

| problem | Nelder-Mead | particle swarm | differential evolution |
|---|---|---|---|
| a rotated ellipsoid, condition 1e6, two knobs, started off the valley (`-seed 1 -maxiter 400 -tol 1e-9`) | 3.2e-19 after 179 | "converged" at **0.27** after 163 | 0 after 991 |
| Rosenbrock in four knobs (`-maxiter 600 -tol 1e-9`) | 3e-18 after 503 | — | "converged" at **2.66** after 703 |
| hunt O1: `-param R2 1k 10 10k -minimize (v(out)-0.2)^2 -method pso -seed 1 -swarmsize 6 -maxiter 20` | 2e-14 | **0.036 at R2 = 10**, on the bound (optimum 250) | — |
| hunt O2: `-param R2 1k 1 1e9 -analysis op -target v(out) 0.9` (R2 = 9k) | — | — | — |
| hunt F6: a compiled conductance refused at g ≤ 0, start g = −1m in [−2m, 5m] | NO SOLUTION after 3 | — | — |

Nelder-Mead is good in two and four smooth dimensions, as it should be; the swarm and DE
"converge" on their stall tests far from the optimum when the valley is at an angle to
the axes (the swarm clamps its velocities, DE's differences shrink along the wrong
directions), a swarm of six collapses onto a wall, LM on O2's box is held at rms 2.5e-5
by its finite-difference step of 1e-3 of the box, a mega-ohm, and a start the model
refuses is never left, because a simplex whose vertices are all penalties satisfies the
convergence test at once.

## What changed

**`-method cmaes`.** Hansen's (μ/μ_w, λ)-CMA-ES with the published default constants.
Each generation samples λ candidates from `N(m, σ²C)`, ranks them by cost, recombines
the best μ = λ/2 into the new mean with log-decreasing weights, and adapts the covariance
`C` (a rank-one update along the evolution path and a rank-μ update from the selected
steps) and the step size σ (cumulative step-size adaptation against the path's expected
length under random selection). λ is `-swarmsize`, default 4 + ⌊3 ln n⌋ (4, 6, 8 for one,
two and four knobs; a value below 4 is raised with a NOTE, E-763's rule), σ₀ = 0.3 in
the cube, candidate 0 of the first generation is the start point, the Gaussian draws come
from E-194's `-seed` stream so a run is reproducible to the digit. The eigendecomposition
`C = B D² Bᵀ` every generation is a cyclic Jacobi sweep on an n × n matrix with
n ≤ 128, microseconds against an analysis.

Three properties made it the first method to add:

- **It is rank-based.** It never reads a cost, only the order of the λ costs, so a
  failed evaluation (`OPT_PENALTY`) is the worst rank and steers the distribution away
  without poisoning a mean or a temperature. From F6's start it reaches g = 1m exactly
  (8 of 197 candidates refused, counted by E-438's NOTE) where Nelder-Mead and LM read NO
  SOLUTION. A generation in which nothing solved moves nothing: σ widens by half and the
  next is drawn; three such generations with no solution ever found end the search, and
  the epilogue reports NO SOLUTION (13 evaluations for a population of 4 on a box the
  model refuses entirely).
- **It learns the scale and the orientation.** On the rotated ellipsoid σ falls by five
  orders while the axis ratio of `C` grows past 200: the distribution has become the
  valley. The objective reaches 0 after 1027 evaluations at `-tol 1e-9`. On Rosenbrock in
  four knobs it reaches 6e-18 after 2217. On O2's nine-decade box `-tol 1e-10` gives rms
  8e-8 (R2 = 8999.99) against LM's 2.5e-5 on the same box.
- **It does not clamp onto a bound.** A candidate outside the cube is re-drawn up to ten
  times, then projected onto it and ranked with a penalty on the squared distance moved,
  scaled to the generation's spread of solved costs; the mean may sit on a wall when the
  optimum is there, and it settles inside the box when it is not. On O1's deck CMA-ES
  alone reaches R2 = 250 (3.9e-14) where the six-particle swarm sat at 10.

Stop tests, in E-762's words: `converged` when σ times the longest axis of `C` falls
below `-tol` (the distribution has shrunk to the tolerance, a length in the cube), or on
the published TolFun rule, when the solved costs of the current generation and the best
costs of the last 10 + 30n/λ generations all lie within `-tol` of each other; `stopped at
-maxiter (N iterations) -- NOT converged` with the NOTE when the generations run out. The
swarm's stall test on the all-time best was tried first and rejected: a start on the
valley floor sees worse samples for many generations while the distribution is still
learning, and the test called that convergence after nine of them. `-verbose` prints one
line per generation: the best cost, σ, the axis ratio and the running evaluation count.

**`-polish`.** After a global method (pso, de, sa, cmaes) the local one runs from the best
point with the full `-maxiter`: Levenberg-Marquardt for a `-target` fit, Nelder-Mead
otherwise, with a first simplex edge of 0.05 in the cube instead of the 0.1 a fresh run
uses (the point is already good). Two lines report it:

```
optimize: polish -- Nelder-Mead from the best point (cost 0.0361376)
optimize: polish converged -- cost 0.0361376 -> 1.27224e-12 in 38 evaluations
optimize: converged, objective = 1.27224e-12 after 105 evaluations
    r2 = 250.002
```

That is O1's exact command with `-polish` appended: the swarm's 0.036 on the bound
becomes the simplex's 1.3e-12 at 250, and the bound NOTE no longer prints. The polish's
status is the final one, since the local criterion met is what "converged" means; it does
not run after an interrupt or when nothing solved. Under Nelder-Mead or LM without
`-starts` the flag prints a NOTE and is ignored (they are the local method); under
`-method nsga2` it is refused (a front has no single best point).

**`-starts <k>`.** The method runs k + 1 times: from the given point and from k
Latin-hypercube points in the cube (one stratum per start per knob, shuffled), each run
with ⌈`-maxiter`/(k+1)⌉ iterations. A population method gets its own seed per start
(`-seed` + the start's index), CMA-ES doubles its population per start (the IPOP restart
rule: 4, 8, 16). Each start prints its verdict, cost and count, the winner is named and
then polished as above (so `-starts` implies `-polish`, and under Nelder-Mead the polish
is the continuation of the winning run with the full budget), and `optimize_start`
publishes the winner's number. On a double well (a global minimum at 0.8, a local one at
0.238) Nelder-Mead from 0.15 converges in the wrong basin at 6.8e-3; with `-starts 4`:

```
optimize: 5 starts -- the given point and 4 Latin-hypercube points, 20 iterations each, the winner polished
optimize: start 1 of 5 (the given point) -- converged, cost 0.00677295 after 20 evaluations
optimize: start 2 of 5 (Latin-hypercube point) -- converged, cost 0.00677295 after 22 evaluations
optimize: start 3 of 5 (Latin-hypercube point) -- converged, cost 0.00677296 after 22 evaluations
optimize: start 4 of 5 (Latin-hypercube point) -- converged, cost 1.2969e-13 after 36 evaluations
optimize: start 5 of 5 (Latin-hypercube point) -- converged, cost 5.78837e-13 after 32 evaluations
optimize: start 4 of 5 won (cost 1.2969e-13)
optimize: polish -- Nelder-Mead from the best point (cost 1.2969e-13)
optimize: polish converged -- cost 1.2969e-13 -> 1.2969e-13 in 32 evaluations
optimize: converged, objective = 1.2969e-13 after 165 evaluations
    v1 = 0.799999
```

A bare `-starts`, `-starts 0` and `-starts abc` are refused by E-763's readers;
`-starts` under nsga2 is refused. The usage line and the unknown-method message list the
seven methods and the two flags. The six existing methods, their reports and their stop
tests are byte for byte what they were, and a deck that names none of the new words runs
as before.

## Checks

`examples/optmethods_examples/verify_optmethods.py` (a new suite, one section group per
method added from the proposal onward; the `optimize` suite keeps the command's original
coverage), 41 checks: [1] the rotated ellipsoid — CMA-ES below 1e-12 at (0.3, 0.7), the
banner's population, the swarm above 1e-3 at the same seed and budget; [2] Rosenbrock in
four knobs to 1e-8, the knobs at 2/3, population 8; [3] O1 — the swarm alone byte for byte
where the hunt found it, the two polish lines, the final line below 1e-9 at R2 = 250 with
no bound NOTE, CMA-ES alone at 250; [4] F6 — Nelder-Mead's NO SOLUTION after 3 unchanged,
CMA-ES at g = 1m with E-438's NOTE counting a minority, a box refused entirely ending
after 13 evaluations as NO SOLUTION; [5] O2 — LM above 1e-5, CMA-ES `-tol 1e-10` below
1e-6 at R2 = 9000, the default `-tol` above 1e-3 (the limit stated); [6] two `-seed 1`
runs identical to the digit and `-seed 2` different, `-maxiter 1` with the NOTE and the
variables, one `-verbose` line per generation with the last count the total less the
final apply, σ down five orders and the axis ratio past 100; [7] `-swarmsize 2` raised
with the NOTE and the `cma` alias, `-polish` under Nelder-Mead a NOTE and the same run,
`-polish` and `-starts` under nsga2 refused, a bare `-starts`, `-starts 0` and
`-starts abc` refused, the usage line and the unknown-method message; [8] `-polish` on a
`-target` fit is LM, three evaluations, R2 = 9000; [9] the double well — Nelder-Mead in
the wrong basin, the `-starts 4` banner, five numbered per-start lines, a winner line
naming the lowest cost, the polish to 0.8 with `optimize_start` and `optimize_status`,
CMA-ES `-starts 2` with populations 4, 8, 16 on the lines and in `-verbose`, the swarm
with three distinct per-start costs; [10] the E-762 variables of a CMA-ES run equal to
the line.

## Limits

- `-tol` is a length in the unit cube for CMA-ES, as it is a relative cost difference for
  the others. On a knob spanning nine decades the default 1e-6 is a kilo-ohm, and the
  method stops there (O2's deck at the default reads rms 5e-3); `-tol 1e-10` reaches
  8e-8. The log-scaled knob of the proposal's section 7 is the right fix for that box and
  is not in this enhancement.
- A polish costs a few dozen evaluations even when the global best is already at the
  optimum (Nelder-Mead's first simplex has to be built and shrunk); on O1's CMA-ES run it
  changed nothing in 40 evaluations.
- A Nelder-Mead `-starts` split gives every start ⌈`-maxiter`/(k+1)⌉ iterations; a start
  that has not converged in its share is reported `maxiter` and can still win.
- `-starts` and `-polish` do not apply to NSGA-II, whose result is a front.

**Update ([E-765](Enhancement-765.md)).** The polish machinery carries Bayesian optimization's hand-off: when the surrogate's criterion is met with budget left, the local method runs with the remaining evaluations as its cap (`polish -- ... up to M iterations (the remaining budget)`) and a first simplex edge of 0.02 instead of 0.05, since a surrogate's best is close; `-polish` after a population method is unchanged. The `-polish` NOTE and the method lists name `bayes`; `-starts` runs the surrogate per start without a hand-off and polishes the winner as before.
