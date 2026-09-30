# Enhancement-766: `optimize -constrain` — constraints for every scalar method through an augmented Lagrangian: "minimise the current subject to v(out) ≥ 0.9" is a command now, the method holds the bound to `-ctol`, the report says whether each constraint is active and what the bound costs (the multiplier as the objective's sensitivity), and a pair that cannot be met reads INFEASIBLE

**Scope:** section 3 of the proposal [more optimizers for `optimize`](../docs/proposals/2026-09-29_optimize-more-methods.md)
(2026-09-29). ngspice only: `frontend/com_optimize.c` (`struct opt_con`, `-constrain <expr>`
with `-max <hi>` and/or `-min <lo>` as a `-spec` takes them, `-ctol <t>`; the constraint
values read after each stage's analysis in `opt_eval`, the augmented terms added to the
cost and, for Levenberg-Marquardt, to the residual vector; `al_solve()`, the outer loop
around `opt_run_method()`; the penalty balanced from the start point; a flat simplex
rebuilt under the constrained solve; `OPT_ST_INFEASIBLE` with its phrase and word; the
per-constraint report; `optimize_feasible`). In passing, `opt_eval` now writes every
residual of a failed stage (the 2026-09-29 hunt's F6 named LM's Jacobian reading stack
garbage there).

**Suites:** `optmethods` 81 of 81 (7 of 81 on the E-763 binary); `optimize` 69 of
69; `psoopt`, `deopt`, `saopt`, `pareto`, `dcenter`, `reuseloops`, `loopguard`, `opt100`,
`optknown`, `optname`, `optpath`, `autobusopt` and `autoopts` unchanged; the full sweep
535 of 535.

## What a design problem is

Every objective the command took was a box: minimise this, fit that, inside `[lo, hi]`
per knob. Real design problems read "minimise the power subject to the gain above 40 dB
and the phase margin above 60 degrees", and the only way to state one was a penalty
hand-rolled into `-minimize`, where a hard wall stalls Nelder-Mead and LM at the boundary
and a soft one moves the optimum. E-206's `-center` bounds metrics too, but as a yield
under process variation, a different question.

## What changed

**The syntax.** `-constrain <expr> -max <hi>` and/or `-min <lo>`, any number of them
(32), with the aliases `-constraint` and `-subject`; the expression is one token like a
`-target`'s, the bounds are strict finite numbers through E-763's readers, a constraint
belongs to the `-analysis` stage it follows (stage 0 before any), and `-ctol <t>` sets
the feasibility tolerance, 1e-4 by default, relative to each bound's own magnitude so a
40 dB gain and a 100 µA current weigh alike. `-min` keeps its E-130 meaning as the
`-minimize` alias except right after a `-constrain` or a `-spec`. A constraint with no
limit, a limit that is not a number, `-ctol 0`, a `-constrain` followed by a flag, a
`-max` before any `-spec` or `-constrain`, and `-constrain` under `-method nsga2` (a front
has no single point to hold) or `-center` are refused with a message.

**The method.** Each constraint side is `g(x) ≤ 0` in units of its bound, the upper side
`(value − hi)/s` and the lower `(lo − value)/s`. While the outer loop runs, `opt_eval`
adds

```
(rho/2) · max(0, g + lambda/rho)²
```

per side to the cost, and gives Levenberg-Marquardt the same as a residual
`sqrt(rho/2) · max(0, g + lambda/rho)` after the targets, so its Jacobian sees the bound.
The outer loop minimises that with the method the user chose — Nelder-Mead, LM, the
swarm, DE, annealing, CMA-ES or the surrogate — reads the objective and the constraint
values at the inner optimum, updates every multiplier `lambda ← max(0, lambda + rho g)`,
raises `rho` tenfold when the largest violation did not fall by a factor of four (a
hundredfold when it did not move at all), and stops when the largest violation is within
`-ctol`, or after ten rounds as INFEASIBLE. Each round prints one line:

```
optimize: 1 constraint (augmented Lagrangian around Nelder-Mead, feasible within 0.0001 of each bound): v(out) >= 0.9
optimize: constraints round 1 -- objective 8.87973e-05, largest violation 0.0134 (relative), penalty 0.00671, converged after 45 evaluations
optimize: constraints round 2 -- objective 9.00026e-05, largest violation 0 (feasible), penalty 0.00671, converged after 75 evaluations
optimize: converged, objective = 9.00026e-05 after 76 evaluations
optimize: constraint v(out) >= 0.9 -- 0.900026, active (multiplier 9.941e-05: raising the bound raises the objective by about that much per unit)
    r1 = 1110.79
    r2 = 10000
```

That is the divider, `-param R1 2k 100 10k -param R2 5k 100 10k -analysis op -minimize
0-i(v1) -constrain v(out) -min 0.9`: the least current with nine tenths of the source on
the output is R2 at its ceiling and R1 = R2/9 = 1111, the constraint active, and the
multiplier is dI*/db = 1/R2 = 1e-4 per unit of the bound — the number a designer wants
next, printed with its direction. CMA-ES, the swarm with `-polish`, the surrogate with
its hand-off and `-starts 2` all reach the same point and the same multiplier within a
few percent; the surrogate and the polish run their own rounds, since the polish holds
the constraint too.

**Two things the probes forced.** A fixed starting penalty of 10 dwarfed an objective of
1e-4 by four orders: the inner method rushed to kill the penalty, hit a box corner and
called it converged with the constraint slack by 0.09. The penalty now starts balanced,
`rho = 2|f0| / viol0²` from one evaluation at the start point, with a `-target` fit's
scale taken as the cost of being wholly off, `Σ (w t)²`, when the start already fits.
And Nelder-Mead's simplex, clamped against the R1 wall from the (1k, 1k) start, went flat
— every vertex the same clamped value in that coordinate, so no reflection could ever
move along it — and passed the convergence test with the dimension undecided (R1 = 100
on the wall, the optimum at 1111 along it). Under the constrained solve a flat simplex is
rebuilt around its best vertex with an inward edge, twice at most; the unconstrained
simplex is left byte for byte as it was, and the general fix is noted below.

**The verdict and the report.** A search that ends violated reads
`INFEASIBLE -- v(out) >= 0.9 missed by 0.0559 after 10 rounds`, `optimize_status` is
`infeasible`, `optimize_converged` 0 and `optimize_feasible` 0 (it is published whenever
a constraint was given). After the report line every constraint side prints its value
and one of: `VIOLATED by <raw miss>`; `active (multiplier <lambda/s>: raising the bound
raises|lowers the objective by about that much per unit)`; `active (at the bound; the
last round landed feasible, so the multiplier estimate is 0)`; or `slack <distance>`.
An inactive constraint changes nothing: the same knob, cost and evaluation count as the
unconstrained run, one round, `slack 0.4`.

**What did not change.** A command without `-constrain` runs every method byte for byte
as before, the `-spec` limits of design centering are untouched, and the E-762 variables
keep their meanings.

## Checks

`examples/optmethods_examples/verify_optmethods.py` sections [20] to [27], 20 checks:
[20] the divider problem under Nelder-Mead from (2k, 5k) and from (1k, 1k) — the banner,
the round lines, R1 = 1111 to 1 %, R2 = 10k, the constraint held to `-ctol`, the active
line with the multiplier within 15 % of 1/R2, `optimize_feasible` 1; [21] the same under
CMA-ES, the swarm with `-polish` and the surrogate (its hand-off line not repeated inside
the rounds, the polish's remaining budget named once); [22] an inactive constraint —
the unconstrained result, `slack 0.4`, no multiplier, one round; [23] the infeasible pair
— ten rounds, the INFEASIBLE line naming the worse side and its miss, both sides
VIOLATED, the three variables; [24] a band with both sides slack, LM with a current bound
in one stage (rms below 1e-6, R1 = R2) and over two stages (the bound active to 1e-4);
[25] seven refusals and `-min` still the `-minimize` alias; [26] a constraint before
`-analysis` (stage 0) and `-starts 2` with every start constrained; [27] a compiled
conductance refused at g ≤ 0 under CMA-ES with `v(out) <= 0.5`, g = 1m and the
constraint active.

## Limits

- The multiplier is an estimate from the last round: exact for a constraint held at its
  bound with the multiplier settled, zero for one that landed feasible within `-ctol` on
  the last round (the report says so), and a few percent off under a method whose inner
  optimum is only as sharp as its own tolerance.
- Ten rounds is the cap; a problem whose violation shrinks slowly ends INFEASIBLE with
  the penalty at 1e12, and the line says how far it got.
- The rebuild of a flat simplex applies only under the constrained solve; an
  unconstrained Nelder-Mead clamped against a bound still stops there (E-764's ellipsoid
  polish shows it). Making the rebuild general is a small enhancement of its own, left for
  a suite-wide look at the runs that finish on a bound.
- Equality constraints are a band (`-min v -max v`) or a `-target`; constraints do not
  reach NSGA-II or design centering.
