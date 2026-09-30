# optmethods_examples — the optimization methods added to `optimize` from the 2026-09-29 proposal on (Enhancements 764, 765, 766, 768)

```
python3 verify_optmethods.py
```

97 checks, one solver (a front-end command; the linear solver does not enter). 74 of 97
on the E-766 binary, which does not know `-method tr` and polishes with Nelder-Mead.

The [`optimize` suite](../optimize_examples/) keeps the command's original coverage; this
one checks the methods' claims on standard test functions posed **inside ngspice**: the
knobs are the dc values of independent sources and a behavioural source computes the
objective from them (`B1 out 0 V = ...`), so an evaluation is a single operating point and
a method's whole search takes milliseconds. A compiled conductance whose parameter is
refused at g ≤ 0 (`optguard.va`) supplies the failing region.

Sections [1]–[10] are [Enhancement-764](../../enhancements_doc/Enhancement-764.md): CMA-ES
(`-method cmaes`), `-polish` and `-starts <k>`.

| section | what it pins |
|---|---|
| [1] | a rotated ellipsoid, condition 1e6: CMA-ES to 1e-12 at (0.3, 0.7), the swarm "converged" above 1e-3 at the same seed and budget; the banner's population 6 (recombining 3) |
| [2] | Rosenbrock in four knobs to 1e-8, every knob at 2/3, population 8 |
| [3] | hunt O1: the six-particle swarm still on the bound at 0.0361376 byte for byte; `-polish` takes it below 1e-9 at R2 = 250 in two reported lines; CMA-ES alone reaches 250 |
| [4] | hunt F6: Nelder-Mead's NO SOLUTION after 3 evaluations unchanged; CMA-ES from the same start at g = 1m with E-438's NOTE counting the refused minority; a box refused entirely ends after 13 evaluations as NO SOLUTION |
| [5] | hunt O2, nine decades: LM above rms 1e-5, CMA-ES `-tol 1e-10` below 1e-6 at R2 = 9000, the default `-tol` above 1e-3 (a length in the cube, stated) |
| [6] | two `-seed 1` runs identical to the digit, `-seed 2` different; `-maxiter 1` with the NOTE and the variables; one `-verbose` line per generation, σ down five orders, axis ratio past 100 |
| [7] | `-swarmsize 2` raised to 4 with a NOTE, the `cma` alias; `-polish` under Nelder-Mead a NOTE and the same run; `-polish`/`-starts` under nsga2, a bare `-starts`, `-starts 0`, `-starts abc` refused; the usage line and the unknown-method message |
| [8] | `-polish` on a `-target` fit is Levenberg-Marquardt: three evaluations, R2 = 9000 |
| [9] | a double well: Nelder-Mead from 0.15 in the wrong basin; `-starts 4` prints the banner, five numbered per-start lines and the winner, polishes to 0.8 and publishes `optimize_start`; CMA-ES `-starts 2` doubles its population per start (4, 8, 16); the swarm gets a seed per start |
| [10] | `optimize_status`, `optimize_converged`, `optimize_evals`, `optimize_cost` of a CMA-ES run equal to the report line |

Sections [11]–[19] are [Enhancement-765](../../enhancements_doc/Enhancement-765.md):
Bayesian optimization (`-method bayes`), a Gaussian-process surrogate with expected
improvement, `-maxiter` an evaluation budget, and the hand-off of what the surrogate leaves
of it to the local method.

| section | what it pins |
|---|---|
| [11] | the divider fit at a budget of 25: the banner with its design size, the hand-off line (N ≤ 16, N + M = 25, its reason), LM's `up to M iterations (the remaining budget)`, R2 = 9000 within 40 evaluations; seeds 2 to 5 likewise |
| [12] | a smooth bowl: the surrogate's best below 1e-5 within 25 evaluations; at a budget of 60 the polish below 1e-10 at (0.3, 0.7) in fewer evaluations than Nelder-Mead alone; the swarm above 500 |
| [13] | the budget honoured: at 30 the polish's `stopped at -maxiter (M iterations) -- NOT converged` with M = 30 − N and the NOTE; at 3 a truncated design and `3 evaluations` in the line, `optimize_status = maxiter` |
| [14] | the surrogate line: predicted cost inside its one-sigma range, `fitted to log cost`, `(no dependence seen)` on exactly the knob the objective does not use |
| [15] | hunt F6: a refused start imputed and left (g = 1m, E-438's NOTE a minority); a box refused entirely ends after three designs (13 evaluations) as NO SOLUTION |
| [16] | a knob the objective ignores: `unchanged -- nothing was optimised` and `v1 100 (no dependence seen)` |
| [17] | `-swarmsize` a NOTE and ignored, `bo` an alias; two `-seed 1` runs identical and `-seed 2` different; `-verbose`'s `(design)` then `max EI` lines, one per evaluation |
| [18] | `-starts 1`: `evaluations each` in the banner, two per-start lines, the winner polished, no per-start hand-off |
| [19] | `optimize_status`, `optimize_converged`, `optimize_evals` equal to the line |

Sections [20]–[27] are [Enhancement-766](../../enhancements_doc/Enhancement-766.md):
constraints, `-constrain <expr> -max <hi> | -min <lo>` with `-ctol`, an augmented
Lagrangian around any scalar method.

| section | what it pins |
|---|---|
| [20] | "minimise the current subject to v(out) >= 0.9" on the divider under Nelder-Mead from (2k, 5k) and from (1k, 1k): the banner, one line per round, R1 = 1111 to 1 %, R2 = 10k, the bound held to `-ctol`, `active (multiplier 1e-4 ...)` within 15 % of dI*/db = 1/R2, `optimize_feasible` 1 |
| [21] | the same under CMA-ES, the swarm with `-polish` and the surrogate with its hand-off (the hand-off line not repeated inside the rounds) |
| [22] | an inactive constraint: the unconstrained knob and cost, `slack 0.4`, no multiplier, one round |
| [23] | an infeasible pair: ten rounds, `INFEASIBLE -- v(out) >= 0.9 missed by ...`, both sides VIOLATED, status infeasible, `optimize_feasible` 0, `optimize_converged` 0 |
| [24] | a band with both sides slack; LM with a current bound in one stage (rms below 1e-6, R1 = R2) and over two stages (the bound active to 1e-4) |
| [25] | seven refusals with their messages; `-min` still the `-minimize` alias without a `-constrain` before it |
| [26] | a `-constrain` before `-analysis` belongs to stage 0; `-starts 2` with every start constrained and the winner polished |
| [27] | a compiled conductance refused at g ≤ 0 under CMA-ES with `v(out) <= 0.5`: g = 1m, active |

Sections [28]–[33] are [Enhancement-768](../../enhancements_doc/Enhancement-768.md): a
derivative-free trust region on a quadratic model (`-method tr`), which the polish and the
surrogate's hand-off now run for a scalar objective. Eight checks of the earlier sections
([3], [7], [9], [12], [13], [18], [21]) expect it in the polish lines and the method lists.

| section | what it pins |
|---|---|
| [28] | a smooth bowl below 1e-12 in at most 15 evaluations, a third or less of Nelder-Mead's; the banner names the method |
| [29] | the rotated ellipsoid below 1e-9 within 60 evaluations, Rosenbrock in four knobs below 1e-7 within 200, a coupled quadratic in ten knobs at Nelder-Mead's value in a third of its evaluations |
| [30] | the bounds inside the subproblem: an optimum on a wall with that knob exactly on the bound, an optimum in a corner |
| [31] | hunt O1's swarm polished in at most 20 evaluations; the surrogate's hand-off on the ellipsoid converged below 1e-9 (the simplex stopped flat in a corner at 0.18) |
| [32] | under `-constrain`: R1 = 1111.1, the multiplier 1e-4 to 2 % |
| [33] | `-maxiter 1`, the `trust` alias, `-polish` a NOTE under it, one `-verbose` line per iteration, a refused start whose axis point solves and one where nothing does, the E-762 variables |
