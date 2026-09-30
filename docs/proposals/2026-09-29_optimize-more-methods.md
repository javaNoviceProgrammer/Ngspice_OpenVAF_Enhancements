# Proposal — more optimizers for `optimize`: CMA-ES, Bayesian optimization, constraints, and the methods behind them

*Scoped 2026-09-29, after the question "let's focus on adding more optimization
algorithms — which powerful ones are worth adding?" Nothing here is implemented. The
command as it stands is Nelder-Mead ([E-130](../../enhancements_doc/Enhancement-130.md))
and Levenberg-Marquardt for `-target` fits, particle swarm
([E-194](../../enhancements_doc/Enhancement-194.md)), differential evolution
([E-195](../../enhancements_doc/Enhancement-195.md)), simulated annealing
([E-196](../../enhancements_doc/Enhancement-196.md)), design centering
([E-206](../../enhancements_doc/Enhancement-206.md)) and NSGA-II
([E-216](../../enhancements_doc/Enhancement-216.md)), with the `.param` fast path of
[E-322](../../enhancements_doc/Enhancement-322.md), the standing circuit of
[E-472](../../enhancements_doc/Enhancement-472.md), and the stop verdicts and strict
arguments of [E-762](../../enhancements_doc/Enhancement-762.md) and
[E-763](../../enhancements_doc/Enhancement-763.md); the code is
[`com_optimize.c`](../../ngspice-46/src/frontend/com_optimize.c). The hunt of
[2026-09-29](../bug_hunts/2026-09-29_optimize-command.md) read that file end to end and
left F4 to F7 and O1 to O8 open; several of the methods below close some of them by
construction, and that is noted where it happens.*

## The plug-in point

Every method is one static function over the **unit cube**: the knobs are scaled to
`u[j]` in [0, 1] from their `-param <name> <init> <lo> <hi>` boxes, and the method
calls `opt_eval(c, u, resid)`, which applies the knobs (`alter`, `altermod`,
`alterparam` or the fast path), runs the `-analysis` stages and returns the scalar cost
— the `-minimize` expression, the weighted sum of squared `-target` residuals, or the
negated worst-case Cpk under `-center` — or `OPT_PENALTY` (1e30) when an analysis did
not solve or the expression was not finite. The function signature is
`(struct optctx *c, double *ubest, double *fbest)`: it starts from `ubest`, leaves the
best point and cost there, polls `ft_intrpt` at the top of every iteration
(E-536/E-537), draws its random numbers from `opt_rand()` seeded by `-seed`
(E-194), and records why it stopped in `c->status` (E-762). The epilogue prints the
report, applies the optimum, publishes `optimize_status`, `optimize_converged`,
`optimize_evals` and `optimize_cost`, and E-501's knob variables. `-maxiter` bounds
the iterations (generations for the population methods, cooling levels for annealing),
`-tol` is the relative stop test (default 1e-6), `-swarmsize` the population.

A new method is therefore one function beside the six that exist, a `-method` name in
the parser, a line in the usage text and a row in the handbook's method list; the
interrupt, status, publish and reuse machinery apply to it without a change. What
matters is which methods buy something the current set cannot. Read as a set, the six
have three gaps:

1. **Nothing is sample-efficient.** Each evaluation is a full analysis — a transient of
   seconds on a compiled model — and the population methods spend hundreds to
   thousands of them. Nothing remembers the shape of what it has already measured.
2. **Nothing copes with an ill-conditioned box.** A knob spanning decades (O2), two
   knobs whose effects are correlated, or a valley at an angle to the axes defeat
   Nelder-Mead's axis-aligned start, LM's fixed finite-difference step (1e-3 of the box)
   and a swarm that collapses onto a wall (O1). The user is expected to fix it by
   choosing the box.
3. **Nothing beyond the box is a constraint**, and every knob is continuous. "Minimise
   power subject to gain above 40 dB and phase margin above 60 degrees" has to be
   hand-rolled as a penalty inside `-minimize`, where a hard penalty stalls the local
   methods at the wall and a soft one moves the optimum. A resistor of 3.317 kΩ cannot
   be bought.

The candidates below are grouped by which gap they close. Sizes are for the method
body in `com_optimize.c` and exclude the suite section and the write-up.

## 1. CMA-ES — the general-purpose global method

*Implemented in [E-764](../../enhancements_doc/Enhancement-764.md), with section 6; the
stop test is the published TolFun rule rather than a stall count, and `-tol` is a length in
the cube (the write-up's limits).*

Covariance Matrix Adaptation Evolution Strategy is the standard for black-box
continuous problems in two to fifty variables. Each generation samples λ candidates
from a Gaussian `N(m, σ²C)`, ranks them by cost, recombines the best μ into the new
mean with log-decreasing weights, and adapts the **covariance** `C` (a rank-one update
along the evolution path and a rank-μ update from the selected steps) and the **step
size** σ (cumulative step-size adaptation on the path's length against its expectation
under random selection). Defaults are the published ones: λ = 4 + ⌊3 ln n⌋, μ = λ/2,
σ₀ = 0.3 in the unit cube, `C = I`; `-swarmsize` overrides λ.

Why it fits this command:

- **It is rank-based.** It never reads a cost, only the order of the λ costs. A failed
  evaluation (`OPT_PENALTY`) is simply the worst rank, so a candidate the model refuses
  steers the distribution away without poisoning a mean or a temperature — the class of
  trouble in F4 (annealing's temperature from the penalty) and F6 (an all-penalty
  simplex) does not arise in this method. A generation in which every candidate fails
  shrinks nothing and moves nothing; after a few such generations the method reports
  `NO SOLUTION`, as E-762 spells it.
- **It learns the scale and the orientation.** After a handful of generations `C`
  holds the valley's directions and the per-knob scales, so a knob spanning decades
  needs no log scaling and correlated knobs need no rotation of the box: it closes O2
  for this method by construction, where LM needs the `-lparam` kind that O2 asks for.
- **It does not collapse onto a bound.** Candidates outside the cube are re-drawn up to
  a few times, then projected with a penalty proportional to the squared distance
  moved — the standard boundary handling — and the mean itself may sit at the wall
  when the optimum is there. O1's six-member swarm at `R2 = 10` with the optimum at 250
  is exactly the case a covariance that has shrunk along that axis handles.
- **It is reproducible** from `-seed` through `opt_rand()`; it needs one Gaussian draw
  (Box-Muller on two uniforms) beside it.

Stop tests, in E-762's words: `CONVERGED` when σ times the largest axis of `C` falls
below `-tol` (the distribution has shrunk to the tolerance) or the generation's cost
range is within `-tol` of its best for `8 + n/4` generations, as the swarm and DE count
their stalls; `MAXITER` when the generations run out; `NO SOLUTION` as above.
Restarts with a doubled population (the IPOP variant) are worth a flag, `-starts <k>`,
and are the same code as section 6's multi-start.

Linear algebra: the sampling needs `C = B D² Bᵀ`, one symmetric eigendecomposition per
generation (or every `n/10` generations, the usual amortisation) of an n × n matrix
with n ≤ `OPT_MAXP` = 128 — a cyclic Jacobi eigensolver, forty lines, is more than
enough at this size and has no dependency. About 350 lines with it. Costs per
evaluation are nothing against an analysis.

## 2. Bayesian optimization — for the slow deck

When one evaluation is a transient of seconds or a corner sweep of minutes, the number
of evaluations is the whole cost, and the right method spends its own arithmetic to
save them. Bayesian optimization fits a **Gaussian-process surrogate** to every point
evaluated so far and chooses the next point by maximising an **acquisition** that
trades the surrogate's predicted improvement against its uncertainty. On a smooth
objective in up to a dozen knobs it finds the optimum in a few tens of evaluations
where DE and the swarm need thousands and Nelder-Mead a few hundred.

The design, kept to what the size of the problem needs:

- **The surrogate.** A GP with a Matérn-5/2 kernel and one length scale per knob
  (automatic relevance determination: a knob the objective does not depend on gets a
  long length scale, and the method effectively drops it — which also answers the
  E-762 `unchanged` case with a diagnosis). Costs are standardised, and log-transformed
  when they span decades, which a `-target` sum of squares always does near its
  optimum. The kernel matrix is N × N for N evaluations; a Cholesky factorisation at
  N ≤ a few hundred is microseconds, so no sparse or inducing-point machinery.
- **The hyperparameters** (length scales, signal variance, a noise floor at the reltol
  jitter of a SPICE objective) by maximising the marginal likelihood — a few dozen
  Nelder-Mead iterations in log-hyperparameter space, re-run every few evaluations.
  `nelder_mead()` cannot be reused as it stands (it calls `opt_eval`); a small
  function-pointer variant of its loop serves both.
- **The acquisition** is expected improvement with a small exploration offset, and it
  is maximised **on the surrogate** by `differential_evolution()`'s loop over a cheap
  callback — thousands of surrogate evaluations cost less than one analysis. The same
  function-pointer refactor as above.
- **The initial design** is `2n + 2` Latin-hypercube points in the unit cube from
  `opt_rand()` (the `-lhs` of design centering stratifies the netlist's own random
  variables, a different thing), the start point among them.
- **Failed evaluations** are imputed at the worst observed cost plus three standard
  deviations, so the surrogate learns that region is bad without a discontinuity; a
  second GP classifying feasible against failed, multiplying the acquisition by the
  probability of a solution, is the published refinement and a natural second step
  when a model refuses a large part of the box.
- **Stop tests.** BO's budget is evaluations, not iterations: `-maxiter` here is the
  evaluation count (the report says so); `CONVERGED` when the best expected improvement
  falls below `-tol` times the observed range. The report adds the surrogate's
  prediction and standard deviation at the optimum, which no other method can give, and
  the length scales — a per-knob sensitivity for free.

About 500 lines: the kernel, the Cholesky solve and log-determinant, the marginal
likelihood, expected improvement, the LHS, and the loop.

## 3. Constraints — an augmented Lagrangian around any scalar method

The objective shape is the third gap, and this one is a wrapper, not a method: it
applies to Nelder-Mead, CMA-ES, BO, the swarm and DE alike, and to LM through its
residuals.

**Syntax.** `-constrain <expr> <= <value>` and `-constrain <expr> >= <value>`, any
number of them (a new `OPT_MAXC`), the expression any metric the objectives take, the
value a strict number (E-763's `opt_strictnum`). Equalities are two inequalities or a
`-target`. Each constraint is scaled by `max(1, |value|)` so a 40 dB gain and a 1e-6
current weigh alike.

**Method.** The standard augmented Lagrangian for inequalities: with
`g_j(x) = ±(expr_j − value_j)` ≤ 0 the inner objective is

```
L(x) = f(x) + (ρ/2) Σ_j [ max(0, g_j(x) + λ_j/ρ)² − (λ_j/ρ)² ]
```

The chosen method minimises `L` to a loosened tolerance, then the multipliers update
`λ_j ← max(0, λ_j + ρ g_j(x*))`, ρ grows tenfold when the largest violation did not
fall by a factor of four, and the outer loop runs until the largest violation is below
a constraint tolerance (`-ctol`, default 1e-4 relative) with the inner method converged,
or ten rounds. Under LM each constraint enters the residual vector as
`sqrt(ρ/2) · max(0, g_j + λ_j/ρ)`, so the Jacobian sees it. A failed evaluation is
`OPT_PENALTY` as before.

**What the user gets** beyond a feasible optimum: the constraint values at the optimum
with the active ones marked, and the multipliers, which are the objective's sensitivity
to each bound — "the phase-margin constraint costs 12 µW per degree" is the number a
designer wants next. A new verdict `INFEASIBLE — largest violation <v> on <constraint>`
(E-762's table gains a row and `optimize_status` a word) when the outer loop ends
violated, and `optimize_feasible` published beside `optimize_converged`.

About 200 lines plus the parser. Section 8 pairs with it: a constraint that must hold
at every corner.

## 4. A trust-region quadratic model — a faster local method

Nelder-Mead is robust and slow: on a smooth objective it spends several evaluations per
useful step and its convergence is linear at best. Powell's BOBYQA family keeps an
**interpolation set** of `2n + 1` points, fits a quadratic model through them (the
Hessian updated by the minimum-Frobenius-norm rule as points are exchanged), minimises
the model inside a trust region intersected with the box, and accepts or rejects the
step by the ratio of actual to predicted decrease, growing or shrinking the radius. On
smooth problems in two to twenty knobs it takes three to ten times fewer evaluations
than Nelder-Mead and respects the bounds natively rather than by clamping.

A simplified variant — diagonal Hessian to start, a dogleg step in the box, a geometry
step when the model is poor — is about 400 lines and is the candidate to become the
`-minimize` default in place of Nelder-Mead once the suites say it is never worse.
Its weakness is the one all interpolation methods share: the reltol-level jitter on a
SPICE objective becomes noise in the model at small radii, so it stops at roughly the
square root of that jitter, as LM does. Section 5 is the complement.

## 5. Pattern search — for the noisy and the nonsmooth objective

Generalised pattern search polls the `2n` coordinate directions at a mesh size Δ,
moves to any improvement (opportunistically, the first found), doubles Δ on success
and halves it on failure, and stops at `Δ < -tol`. MADS adds a randomly rotated dense
set of directions each iteration so the poll is not blind to a diagonal valley. It has
a convergence proof for nonsmooth functions and needs no model, no gradient and no
population: a failed evaluation is a failed poll and nothing more, and an objective
built from a measured delay, a threshold crossing or a counted edge — piecewise
constant, with steps — is searched exactly as a smooth one. It is also the natural
**polish** after a global method. About 150 lines.

## 6. Multi-start and polish — the strategy that closes O1

*Implemented in [E-764](../../enhancements_doc/Enhancement-764.md): `-polish` and
`-starts <k>` as below, `-starts` implying the polish, `optimize_start` published.*

Two flags rather than a method, and mostly existing pieces:

- `-polish` on the population methods (the swarm, DE, annealing, CMA-ES) runs the
  local method — Nelder-Mead, or LM when there are `-target`s, or section 4's when it
  exists — from the global best with the remaining budget, and reports both costs. O1's
  swarm at 0.036 becomes Nelder-Mead's 2e-14 from the point the swarm found.
- `-starts <k>` runs the local method from k Latin-hypercube starts (plus the given
  one), each with `1/(k+1)` of `-maxiter`, and polishes the best. It is the cheapest
  global search there is when the objective has a few basins, and the same code gives
  CMA-ES its restarts.

About 100 lines. The report says which start won, so a user learns whether the problem
was multimodal at all.

## 7. Discrete knobs — what can be bought

Two knob kinds beside `-param`, `-mparam` and `-dparam`:

- `-iparam <name> <init> <lo> <hi>`: an integer — a finger count, a stage count, a
  number of unit cells behind a `.param`.
- `-eparam <name> <init> <lo> <hi> e24|e96|e192`: a value snapped to the E series
  (decade-periodic, so the natural search variable is log-scaled, which also gives
  O2's `-lparam` for free as `-eparam ... cont`).

The search stays continuous in the unit cube and the value is **snapped at
evaluation**, so every method works unchanged; the objective becomes piecewise constant
in those knobs, which is nothing to the rank-based and polling methods (CMA-ES, DE, the
swarm, pattern search) and fatal to a finite difference, so LM and section 4 refuse a
deck with a discrete knob by name, and Nelder-Mead warns. The finish is a **lattice
polish**: for each discrete knob try one step up and one down from the snapped optimum,
accept improvements, repeat until none — coordinate descent on the lattice, a dozen
evaluations. The report prints the snapped values and the cost at the continuous
optimum beside them, so the user sees what the series cost.

## 8. Worst case over corners — robust design

`-corners <name>,<name>,...` (names from the models' `corner` attributes,
[E-654](../../enhancements_doc/Enhancement-654.md) to
[E-669](../../enhancements_doc/Enhancement-669.md); `tt` is the nominal) runs every
`-analysis` stage once per corner with the corner moved through the `corner` variable
E-669 reads, and the cost is the **worst** over corners — the largest `-minimize`
value, the largest `-target` residual norm, the most violated constraint under
section 3. This is minimax design: the optimum is the design that meets the spec at
its worst corner. It differs from `-center`, which optimises a yield against
statistical variation; the two compose (a worst-case Cpk over corners) but that is a
later step. The question for the fold is whether moving the corner between the stages
of one evaluation keeps E-472's standing circuit or costs a re-source per corner; the
handbook says `set corner=<name>` works between runs, which suggests the former.

Mostly plumbing, about 150 lines; the multiplied evaluation cost is the reason
section 2 comes before it.

## 9. A second multi-objective method

NSGA-II's crowding distance degrades above three objectives — the front becomes a
cloud and selection pressure toward it collapses. MOEA/D decomposes the problem into
a set of scalar subproblems along evenly spread weight vectors (Tchebycheff
aggregation), each solved with its neighbours' help, and scales to many objectives
with a population of the weight vectors' size; NSGA-III does the same with reference
points inside the NSGA-II frame. Either is about 300 lines and reuses `opt_eval_objs`
and the Pareto report. It is the lowest priority here: two and three objectives are
the common case and NSGA-II serves them; the open F5 (failed evaluations on the front)
should be fixed in `opt_eval_objs` first, where any second method would inherit it.

## The candidates side by side

| section | method | closes | evaluations it saves | size |
|---|---|---|---|---|
| 1 | CMA-ES | gap 2; O1, O2 and the F4/F6 class for this method | tens to hundreds over the swarm and DE on an ill-conditioned box | ~350 lines |
| 2 | Bayesian optimization | gap 1 | one to two orders on a slow deck, ≤ 12 knobs | ~500 lines |
| 3 | augmented Lagrangian, `-constrain` | gap 3 | — (a new problem class) | ~200 lines |
| 4 | trust-region quadratic model | a faster local default | 3 to 10× over Nelder-Mead on smooth objectives | ~400 lines |
| 5 | pattern search / MADS | noisy and stepped objectives | — (robustness) | ~150 lines |
| 6 | `-polish`, `-starts` | O1 | the local methods' precision after a global search | ~100 lines |
| 7 | `-iparam`, `-eparam` | gap 3, buildable designs; O2's log knob | — | ~250 lines |
| 8 | `-corners` worst case | robust design | — (multiplies them) | ~150 lines |
| 9 | MOEA/D or NSGA-III | four or more objectives | — | ~300 lines |

## What this does not change

The six methods that exist stay byte for byte, including their reports and stop
tests, so every suite that names them holds. Design centering, NSGA-II, the `.param`
fast path, E-472's reuse and E-763's argument rules are untouched; the new flags are
parsed by the same strict readers. A deck that names no new flag runs as before. The
old binary refuses `-method cmaes` with the usage line, so the old-binary counts fall
by exactly the new sections, as they did for E-762 and E-763.

## Verification to pin (the suite)

The `optimize` suite is at 69 checks and a run of some minutes; the new methods go
into a new suite, `optmethods_examples`, one section per method, so a method's
checks can be run alone. A deck whose objective is a **function of the knobs alone** —
`.param` knobs feeding a behavioural source, `-minimize` of its voltage — lets the
suite pose the standard test functions inside ngspice:

- **CMA-ES**: a rotated ellipsoid with a condition number of 1e6 reached to 1e-10 in the
  unit cube where the swarm and DE stall above 1e-4 at the same budget; Rosenbrock in
  four knobs; O2's deck (`R2` on `[1, 1e9]`) fitted to the digits LM gets on the narrow
  box; the guard conductance deck of the hunt (`guardi.va`, a region the model refuses)
  reaching the optimum from a failing start (F6 for this method) and `NO SOLUTION`
  when the whole box fails; two runs with `-seed 1` byte-identical, `-seed 2`
  different; `-maxiter 1` reads `stopped at -maxiter ... NOT converged`.
- **Bayesian optimization**: the divider fit to 1e-6 in at most 25 evaluations where
  Nelder-Mead takes about 60; a knob the objective ignores gets a length scale above
  the box and the report says so; a deck that fails on half the box is solved on the
  other half; `-maxiter` counts evaluations and the report says "evaluations".
- **Constraints**: minimise the divider's dissipation subject to `v(out) >= 0.9`: the
  optimum sits on the constraint within `-ctol`, the multiplier is the derivative of
  the dissipation along the constraint to within a few percent, the report marks it
  active; the same under `-method lm` with a `-target`; an unsatisfiable pair reads
  `INFEASIBLE` and `optimize_feasible` is 0; a constraint on a metric that is never
  binding leaves the unconstrained optimum unchanged.
- **Trust region and pattern search**: the smooth ellipsoid in fewer evaluations than
  Nelder-Mead to the same `-tol`; a stepped objective (a `floor()` of a metric) where
  pattern search finds the lowest step and Nelder-Mead stalls on the first plateau.
- **`-polish` and `-starts`**: O1's exact command reaching Nelder-Mead's cost; a
  two-basin deck where the given start is in the wrong basin and `-starts 4` reports
  the winning start.
- **Discrete knobs**: an `-eparam ... e24` optimum is an E24 value, the lattice polish
  improves on the snapped continuous optimum at least once in the suite's deck, LM
  refuses the deck by knob name.
- **Corners**: a two-corner model where the nominal optimum violates the spec at `ss`
  and the worst-case optimum meets it at both, at the cost the report prints.

Every section: `optimize_status`, `optimize_converged`, `optimize_evals` and
`optimize_cost` agree with the report line, and an interrupt reads `INTERRUPTED`.

## Where the code goes

- `com_optimize.c`: `cma_es()`, `bayes_opt()`, `trust_region()`, `pattern_search()`
  beside their siblings, the same signature; `augmented_lagrangian()` wrapping the
  scalar dispatch (`use_lm` and its neighbours); the method table gains `cmaes`,
  `bayes`, `tr`, `ps` and their aliases; `-constrain`, `-ctol`, `-polish`, `-starts`,
  `-corners`, `-iparam`, `-eparam` in the parser under E-763's rules; `OPT_ST_INFEASIBLE`
  with its phrase and word; a Gaussian draw beside `opt_rand()`; a function-pointer
  variant of the Nelder-Mead and DE loops so BO can run them on its surrogate.
- The linear algebra — Jacobi eigensolver, Cholesky factor and solve, log-determinant
  — as static helpers in a sibling `optlinalg.c` with a small header, so
  `com_optimize.c` (2 300 lines today) does not carry it.
- `struct optctx`: the constraint table, the discrete-kind flags per knob and their
  series, the corner list, the polish and starts flags.
- The handbook's [Fitting and optimizing: `optimize`](../handbook/03-ngspice-workflows.md)
  subsection: the method list with a line on when to choose each, the constraint
  syntax, the discrete knobs, the status table's new row; the catalog area
  "Optimization & parametric sweeps".

## Order of work

1. **CMA-ES** (section 1), with `-polish` and `-starts` (section 6) in the same fold
   since the restart loop is shared: the largest gain per line, no new syntax beyond
   the method name and two flags, and it closes O1 and O2 for the global search.
   *Done: [E-764](../../enhancements_doc/Enhancement-764.md).*
2. **Bayesian optimization** (section 2): the fold that changes what is practical on a
   slow deck; the function-pointer refactor of the Nelder-Mead and DE loops comes
   with it.
3. **Constraints** (section 3): the fold that changes what problems the command can
   state.
4. **The trust-region method** (section 4) and **pattern search** (section 5), one fold
   each; then the question of the `-minimize` default.
5. **Discrete knobs** (section 7), which also settle O2's log-scaled knob.
6. **Worst case over corners** (section 8), after the corner move's cost is measured.
7. **A second multi-objective method** (section 9), after F5 is fixed in
   `opt_eval_objs`.
