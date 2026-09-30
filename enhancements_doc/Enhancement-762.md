# Enhancement-762: `optimize` says why it stopped — every stop read "converged" (the iteration cap, a run in which no evaluation solved, one whose objective never moved; only an interrupt was told apart); the methods now record their reason, the report opens with it, a NOTE follows the cap, and `optimize_status`, `optimize_converged`, `optimize_cost` and `optimize_evals` are published for a script to test

**Scope:** F1 of the 2026-09-29 `optimize` hunt. ngspice only: `frontend/com_optimize.c`
(`OPT_ST_*`, an `optctx.status` each method sets where it breaks, `opt_status_word()`,
`opt_status_phrase()`, `opt_publish_outcome()`, the epilogue's two verdicts). The
converged line is byte-for-byte what it was, so nothing that parses it changes; the other
stops change the phrase the line opens with.

**Suites:** `optimize` 54 of 54 (44 of 54 on the E-761 binary: the new section [19]),
`reuseloops` 17 of 17 per solver (its regex now accepts any stop phrase), `pareto`,
`dcenter` unchanged; the full sweep 534 of 534.

## What was wrong

The report's last line is the one a reader or a script acts on, and it said `optimize:
converged, objective = ... after N evaluations` whatever had ended the search:

| run | what ended it | reported |
|---|---|---|
| Nelder-Mead with `-maxiter 1` | the cap, after 5 evaluations, objective 9.8e-5 | converged |
| Levenberg-Marquardt with `-maxiter 1` | the cap, 4 evaluations, sum-sq 0.13 | converged |
| particle swarm with `-maxiter 1` | the cap, 11 evaluations | converged |
| an analysis that never solves | objective 1e30, three evaluations | converged, then two NOTEs |
| a start inside a region the model refuses (hunt F6) | nothing could move | converged |
| a knob the objective does not depend on | three equal evaluations | converged, then E-499's NOTE |

E-499's NOTEs (the objective never moved, a parameter on a bound) and E-438's (N
evaluations did not solve) follow the line and soften it; E-537 made the interrupt say
"INTERRUPTED -- best point so far". The word itself was never qualified, and nothing was
published for a `.control` script to branch on: the knob values (`optimize_<name>`, E-501)
and the centering yield were, the outcome was not.

## What changed

- **Each method records its stop.** `OPT_ST_CONVERGED` where its own criterion breaks the
  loop (the tolerance tests of Nelder-Mead and Levenberg-Marquardt, the stall counters of
  particle swarm and differential evolution; LM's "no step of any length lowers the cost"
  is a minimum to within the finite-difference accuracy and counts as convergence, which
  is also what the smooth fits end on), `OPT_ST_MAXITER` when the loop runs out,
  `OPT_ST_COMPLETED` for the two methods whose stop is a schedule (annealing's cooling
  levels, NSGA-II's generations), `OPT_ST_INTERRUPTED` beside E-537's flag.
- **The epilogue adds two verdicts.** A best cost still at the penalty means no evaluation
  ever solved (`OPT_ST_NOSOLVE`); an objective that took the same value at every
  evaluation means nothing was optimised (`OPT_ST_UNCHANGED`; E-499's NOTE still explains
  the usual causes). The interrupt outranks both.
- **The line opens with the phrase**, for the scalar, least-squares and centering reports
  alike: `converged` (unchanged), `stopped at -maxiter (N iterations) -- NOT converged`
  followed by `optimize: NOTE -- the iteration cap ended the search before its own
  criterion did; raise -maxiter, or loosen -tol if the reported value is close enough.`,
  `cooling schedule complete (N levels)`, `NO SOLUTION -- no evaluation solved`,
  `unchanged -- nothing was optimised`, `INTERRUPTED -- best point so far`.
- **The outcome is published.** `optimize_status` is a string shell variable (`converged`,
  `maxiter`, `completed`, `nosolve`, `unchanged`, `interrupted`); `optimize_converged` (1
  for a search that ended on its own criterion or completed its schedule),
  `optimize_evals` and `optimize_cost` are vectors and shell variables, through the same
  `dc_set_result` E-501 gave the knob values. NSGA-II publishes the status and the count
  (its result is a front, not a cost).

## Checks

`optimize` section [19]:

| check | result |
|---|---|
| Nelder-Mead, Levenberg-Marquardt and particle swarm at `-maxiter 1` | `stopped at -maxiter (1 iteration) -- NOT converged`, the NOTE, `optimize_status=maxiter`, `optimize_converged=0` |
| a converged run | the line reads `converged, objective = ... after N evaluations` as before; `optimize_status=converged`, `optimize_converged=1`, `optimize_evals` = N and `optimize_cost` = the line's value |
| an analysis that never solves | `NO SOLUTION -- no evaluation solved`, `nosolve` |
| a knob the objective does not depend on | `unchanged -- nothing was optimised`, `unchanged` |
| simulated annealing, ten levels | `cooling schedule complete (10 levels)`, `completed`, `optimize_converged=1` |

## Limits

- `-maxiter` is the schedule for annealing and NSGA-II, so running it out is their normal
  end and reads `complete`, not `stopped`.
- LM's "cannot reduce further" is reported as converged: at a minimum no step reduces the
  cost, and the command cannot tell that from a rugged region where every trial step
  happened to be uphill. E-499's bound NOTE and E-438's failure NOTE still qualify it.
- A search that never leaves a failing region (hunt F6) now reads `NO SOLUTION`; it still
  does not look for a solvable start. That is F6's fold.

**Update ([E-764](Enhancement-764.md)).** `-method cmaes` records `converged` on its own two criteria (the distribution shrunk below `-tol`, or the TolFun rule) and `maxiter` when the generations run out; a box the model refuses entirely ends after three all-failed generations and reads NO SOLUTION here. With `-polish` the local method's status is the final one, and with `-starts k` each start's verdict is printed on its own line (`start 2 of 5 (Latin-hypercube point) -- converged, cost ...`) with `optimize_start` published beside these variables.

**Update ([E-765](Enhancement-765.md)).** Under `-method bayes` the cap is an evaluation budget and the phrase says so: `stopped at -maxiter (N evaluations) -- NOT converged`; the polish that follows the surrogate's hand-off counts iterations again and its status is the final one. A knob the objective ignores still reads `unchanged`, and the surrogate line adds the diagnosis (`v1 100 (no dependence seen)`).

**Update ([E-766](Enhancement-766.md)).** A seventh verdict: `INFEASIBLE -- <expr> >= <bound> missed by <d> after N rounds` when a `-constrain` could not be met in ten rounds of the augmented Lagrangian, `optimize_status` = `infeasible`, `optimize_converged` 0; `optimize_feasible` (1 or 0) is published whenever a constraint was given. A constrained search that ends feasible carries the inner method's own verdict.

**Update ([E-768](Enhancement-768.md)).** `-method tr` records `converged` when its model expects less than `-tol` of decrease and has just proven itself, or when its radius has come down to `-tol`, and `maxiter` when the iterations run out; the polish lines that carry the final verdict now name the trust region for a scalar objective.
