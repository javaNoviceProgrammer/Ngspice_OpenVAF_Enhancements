# Bug hunt 2026-09-29 — the `optimize` command

**Scope.** `frontend/com_optimize.c` at E-761 (2112 lines: Nelder-Mead, Levenberg-Marquardt,
particle swarm, differential evolution, simulated annealing, NSGA-II, design centering,
the `.param` fast path, setup reuse), read end to end and probed with decks on the current
build. The harness is a Python runner over a divider and a compiled conductance whose
parameter is refused outside `(0:inf)` (an instance-typed `guardi.va`), so a search can be
sent into a region where the analysis fails. Nothing here is fixed yet; each finding has
its reproduction.

| id | finding | severity |
|---|---|---|
| [F1](#f1--every-stop-is-reported-as-converged) | every stop is reported as "converged": at `-maxiter`, after all evaluations failed, when LM could not reduce; only the interrupt is told apart | **high** — the one word a script or a reader acts on |
| [F2](#f2--the-knob-and-target-numbers-are-lenient) | `-param R2 1k abc 10k` takes `abc` as 0 and `10o` as 10 in silence; an init outside `[lo, hi]` is clamped without a word; a `-target` weight of −1 is accepted; a bare `-method`, a second `-minimize` under a scalar method and `-swarmsize 3` are absorbed in silence | **medium** — E-499 made the options strict and left the knobs and targets as they were |
| [F3](#f3--an-expression-or-command-that-begins-with-a-minus-sign-is-read-as-a-flag) | `-minimize -v(out)` and `-target v(out) - v(in) 0.4` are torn apart at the `-`: the first ends in "incomplete or empty netlist", the second fits to a target of 0 and answers a different question | **medium** — a negated objective is the natural way to maximise |
| [F4](#f4--simulated-annealing-seeds-its-temperature-from-the-failure-penalty) | a start inside the failing region gives `T0 = 7.9e29`; after 40 cooling levels T is still `1e26`, every uphill move is accepted, the schedule is meaningless | **medium** |
| [F5](#f5--nsga-ii-ignores-failed-evaluations) | a design the model refuses (`g = −0.0011`) sits on the reported Pareto front with a neighbour's objectives; no NOTE; E-438's check and E-472's reuse are missing from the multi-objective path | **high** — the front is the answer |
| [F6](#f6--a-search-started-inside-a-failing-region-never-leaves-it) | NM stops after 3 evaluations and LM after 15, both "converged" at the failing start; LM's residual vector is left uninitialised on a failed stage | **high** |
| [F7](#f7--the-dparam-optimum-is-not-written-into-the-deck-when-the-fast-path-is-armed) | on a deck of 80 weighted devices or more the fitted `.param` value never reaches the deck: `listing param` shows the initial value and a user `reset` reverts the circuit (0.9 → 0.5); a small deck keeps it | **high** — the answer evaporates at the next reset, and only for large decks |
| [O1](#observations) | particle swarm with a six-member swarm collapses onto a bound (0.036 against 2e-14 for NM) and its stall test calls it converged; default swarms are fine but stop at 1e-6, four to seven orders above the local methods | observation |
| [O2](#observations) | a knob spanning decades: LM's fixed finite-difference step in linear normalised space costs four orders of accuracy on `[1, 1e9]` | observation |
| [O3](#observations) | after a fit, a user `reset` drops the `-param`/`-mparam` optimum (alter semantics) and keeps the `-dparam` one | observation |
| [O4](#observations) | `-maximize` exists for NSGA-II only; under a scalar method it prints the usage line | observation |
| [O5](#observations) | knob names are not validated before the search | observation |
| [O6](#observations) | the Pareto front's parameter columns are printed, not published | observation |
| [O7](#observations) | no convergence history, no `optimize_cost`/`optimize_evals` vectors | observation |
| [O8](#observations) | the handbook has no section on the command | observation |

The harness: `scratchpad/opt/run.py` (a divider `DIV`, decks written as `_<tag>.cir`),
`guard.va` (a model-level `g`, which `alter @n1[g]` refuses with a clear error — the
first probes were invalid for that reason) and `guardi.va` (`(* type="instance" *)`).

## F1 — every stop is reported as "converged"

**Observed.** The final line reads `optimize: converged, ...` whatever ended the search,
except an interrupt (E-537):

| run | what ended it | reported |
|---|---|---|
| `-param R2 100 10 100k -analysis op -minimize (v(out)-0.9)^2 -maxiter 1` | the iteration cap, after 5 evaluations, objective 9.8e-5 | converged |
| the same as `-target v(out) 0.9 -method lm -maxiter 1` | the cap, 4 evaluations, sum-sq 0.13 (rms 0.36) | converged |
| `-method pso -maxiter 1 -swarmsize 5` | the cap, 11 evaluations, objective 1.6e-3 | converged |
| `-analysis tran 1` (invalid, every evaluation fails) | nothing solved, objective 1e30 | converged, then two NOTEs |
| a start inside the failing region (F6) | nothing could move | converged |

Levenberg-Marquardt also breaks out when twelve lambda increases cannot reduce the cost
("cannot reduce further"), which is a stall, not a convergence, and is reported the same
way. E-499's NOTEs (the objective never moved, a parameter on a bound) and E-438's (N
evaluations did not solve) follow the line and soften it, but the word itself is what a
script reading the console, or a reader skimming, takes.

**Where.** `com_optimize()`'s report: `c.interrupted ? "INTERRUPTED -- best point so far" :
"converged"`. The methods return through their loops without saying why they stopped:
`levenberg_marquardt` breaks on `!accepted` or on the tolerance or runs out of `maxiter`;
`nelder_mead` on the tolerance or `maxiter`; the population methods on the stall counter or
`maxiter`.

**Fix.** Each method records a status (converged on its criterion, stopped at `-maxiter`,
stalled, no solvable evaluation, interrupted), the report prints the matching word and the
NOTE for the cap ("raise -maxiter or loosen -tol"), and the status is published as a
vector and a shell variable (`optimize_status`) beside `optimize_cost` and
`optimize_evals` (O7), so a `.control` loop can branch on it.

## F2 — the knob and target numbers are lenient

**Observed.**

| command fragment | what happened |
|---|---|
| `-param R2 1k abc 10k` | `abc` became `lo = 0`; the fit ran over `[0, 10k]` and converged, no message |
| `-param R2 1k 10o 10k` | `10o` became 10 |
| `-param R2 5k 10 1k` (init above `hi`) | the start was clamped to `hi`; the only word was E-499's "finished ON a search bound" at the end |
| `-target v(out) 0.9 -1` (weight −1) | accepted; the sign is lost in the square |
| `... -method` (no argument) | Nelder-Mead in silence |
| `-minimize A -minimize B` with Nelder-Mead | B ignored in silence (it is an NSGA-II objective) |
| `-method de -swarmsize 3` | "population of 5 vectors" — bumped without saying why (DE needs four distinct members) |

**Where.** `com_optimize()`'s parser: `optnum()` (an `ft_numparse` with an `atof`
fallback) for `<init> <lo> <hi>`, the `-target` value and weight; E-499's `opt_strictnum`
covers `-maxiter`, `-tol`, `-swarmsize`, `-seed`, `-samples` only. No check of `lo <= init
<= hi`, of `weight > 0`, of a `-method` without an argument, of a second scalar objective.

**Fix.** The same rule E-499 gave the options: refuse a knob value, target or weight that
is not a whole number token; refuse an init outside the box (or say it is being moved to
the bound); refuse a weight that is not positive; refuse a bare `-method`; refuse a second
`-minimize`/`-maximize` unless the method is `nsga2`; say when a population is raised to
its minimum.

## F3 — an expression or command that begins with a minus sign is read as a flag

**Observed.** `-minimize -v(out)` (the natural way to maximise `v(out)`) prints
`optimize: unrecognized token '-v(out)'`, then the usage line, and in batch mode ngspice
follows with "Error: incomplete or empty netlist ... no simulations run!", which points at
the deck rather than the command. `-target v(out) - v(in) 0.4` (a target expression with
spaces, which the header says is not allowed) takes `v(out)` as the expression, `-` as the
value (0 through `optnum`), prints `unrecognized token 'v(in)'` and `0.4`, and then RUNS
the fit to a target of 0: "converged ... 1 of 1 parameter finished ON a search bound".

**Where.** `is_flag()`: any `-<letter>` token ends `collect_until_flag`; `-v(out)` is
`-v`, the verbose flag's spelling. `-target`'s value goes through `optnum`, which returns 0
for `-`.

**Fix.** Accept a quoted expression as one token (the lexer keeps `"..."` and
`collect_until_flag` already unquotes), and say so in the message: "an expression that
begins with `-` must be quoted, or written as `0-v(out)`"; a `-target` value that is not
a number is refused (F2's rule), which stops the spaced expression from running.

## F4 — simulated annealing seeds its temperature from the failure penalty

**Observed.** `guardi` (`g from (0:inf)`), `-param @n1[g] -1m -2m 5m`
`-analysis op -minimize (v(out)-0.5)^2 -method sa -seed 3 -maxiter 40 -verbose`:

```
level 1    T 7.94e+29  best cost 0.0252893  (25 evals)
level 20   T 1e+28     best cost 3.15282e-06
level 40   T 1e+26     best cost 1.43373e-08
```

The same run from `g = 2m` starts at `T = 0.0277` and ends at `3.48e-6`. With T at
1e26 every uphill move is accepted (`exp(-d/T)` is 1 for any finite d): the walker is a
random walk that happens to keep its best point, and the four-decade cooling schedule
never reaches the objective's scale. The result was still 1.4e-8 here because the box is
one-dimensional and the walk stumbled onto it; in more dimensions it would not.

**Where.** `simulated_annealing()`: `T0` is the mean `|fn - fx|` over twelve random
probes, and `fx` is the start's cost — the penalty 1e30 when the start fails. The probes
that fail are excluded (`fn < OPT_PENALTY`), the start is not.

**Fix.** When the start fails, move the walker to the best solvable probe before the
temperature is estimated, and estimate it from the spread among the solvable probes only.

## F5 — NSGA-II ignores failed evaluations

**Observed.** `-param @n1[g] 1m -2m 5m -analysis op -minimize (v(out)-0.5)^2`
`-maximize v(out) -method nsga2 -seed 1 -maxiter 5 -swarmsize 8` prints an eight-design
front that includes

```
    0.147895 0.884572 | 0.000130491
    0.147895 0.884572 | -0.00111304
```

The second design is refused by the model (a negative `g`); its two objectives are the
first design's, read from the plot the failed analysis left standing. No NOTE mentions a
failed evaluation. The same box under `-method pso` reports "4 of 49 evaluations did not
solve and were scored as worst-case" (E-438).

**Where.** `opt_eval_objs()` runs the analysis and evaluates the objectives without the
`opt_run_failed()` check that `opt_eval()` has had since E-438, and without
`opt_reuse_ask()` (E-472), so every NSGA-II evaluation also rebuilds the circuit. `nfailed`
is never counted on this path.

**Fix.** The same three lines `opt_eval` has: after the analysis, `sim_status != 0` scores
every objective 1e15 (dominated by any solvable design, which NSGA-II then drops from the
front) and counts `nfailed`; ask for the setup reuse; print E-438's NOTE.

## F6 — a search started inside a failing region never leaves it

**Observed.** From `g = -1m` in `[-2m, 5m]`:

| method | evaluations | reported |
|---|---|---|
| Nelder-Mead | 3 | converged, objective 1e30; "the objective was 1e+30 at every one of the 3 evaluations"; "3 of 3 did not solve" |
| Levenberg-Marquardt, two stages | 15 | converged, sum-sq 1e30, the same two NOTEs |

Nelder-Mead's convergence test is `fv[hi] - fv[lo] <= tol * (...)`: a simplex whose every
vertex is the penalty satisfies it at once (its first vertices lie 0.1 of the box from
the start, `g = -0.3m`, still refused). LM's finite-difference probes lie 1e-3 of the box
from the start (`g = -0.993m`), still refused; its Jacobian is then built from
`r0`/`rj`, stack arrays that `opt_eval` never filled — on a failed stage it sets the cost
to the penalty and `break`s out of the stage loop before the targets are written — so the
step direction is whatever the stack held. Here everything failed and the garbage did not
matter; a start whose first stage fails and second solves would compute a real step from
half-garbage residuals.

**Where.** `nelder_mead()` (the test), `levenberg_marquardt()` (the fixed probe step, the
uninitialised `r0`/`rj`), `opt_eval()` (the `break` before `resid` is written).

**Fix.** `opt_eval` fills every residual with the push-away value (1e15) on a failed
stage. A start that fails is not a start: probe the box (a dozen random points, as the
annealer does) and begin from the best solvable one, saying so; a Nelder-Mead simplex
whose vertices are all penalties expands rather than converges.

## F7 — the `-dparam` optimum is not written into the deck when the fast path is armed

**Observed.** A chain of 100 resistors into `RL out 0 {rr}`, `.param rr=1k`,
`optimize -dparam rr 1k 100 10k -analysis op -target v(out) 0.9`, then `op`, `reset`,
`op`, `listing param`:

| deck | fast path | after the fit | after a user `reset` | `listing param` |
|---|---|---|---|---|
| 100 resistors | armed ("no per-eval reset") | v(out) = 0.9 | v(out) = 0.5 | `rr = 1000` |
| 2 resistors | not armed | v(out) = 0.9 | v(out) = 0.9 | `rr = 9000` |

The small deck's fit goes through `alterparam`, which rewrites the stored deck, so the
optimum survives a reset. The large deck's fit pushes the value in place (E-322) and never
touches the deck; the final "leave the circuit at the optimum" evaluation pushes in place
too. The next `reset` — the user's, or any command's internal one — restores `rr = 1k`.
Which of the two a user gets depends on a device count they have no reason to know about
(80 weighted primitives, 3 OSDI instances).

**Where.** `opt_eval()`: the `fp_armed` branch calls `opt_fp_apply` and skips
`alterparam`; the final apply in `com_optimize()` is an ordinary `opt_eval`.

**Fix.** After the search, apply the final `-dparam` values once through `alterparam`
(with the fast path's in-place push kept for the evaluations), so the deck carries the
optimum on both paths; `optimize_rr` already publishes the number. O3 documents what a
reset does to the other knob kinds.

## Observations

**O1 — particle swarm on a bound.** `-param R2 1k 10 10k -minimize (v(out)-0.2)^2 -method
pso -seed 1 -swarmsize 6 -maxiter 20`: objective 0.036 at `R2 = 10` (the optimum is 250,
2.4 % of the box from the bound) — the swarm collapses onto the wall, the velocities clamp
and the eight-iteration stall test calls it converged; Nelder-Mead reaches 2e-14. With the
default swarm (14) five seeds reach 2.5e-6 to 4e-11 and differential evolution 1.7e-15 to
6.6e-11. Two things worth having: velocities that reflect at a bound instead of clamping,
and a local polish (Nelder-Mead or LM from the global best) at the end of every global
method, which would give a global search the local methods' precision.

**O2 — a knob spanning decades.** `-param R2 1k 1 1e9 -target v(out) 0.9 -method lm`:
rms 2.5e-5 after 41 evaluations, against 2.3e-9 on `[1, 100k]`; the finite-difference
step is a fixed 1e-3 of the box (1e6 Ω here), so the secant is nothing like the
derivative until the search has shrunk the problem. Nelder-Mead is unaffected. A
log-scaled knob kind (`-lparam <name> <init> <lo> <hi>`, searched in `log(x)`) is what
device extraction needs — saturation currents, capacitances and resistances all live on
decades — and an adaptive step (relative to the current value) would help the linear one.

**O3 — what a reset keeps.** After a fit, a user `reset` re-sources the deck: `-param`
and `-mparam` optima (in-place alters) are gone, a `-dparam` optimum stays when F7 is
fixed. E-544 journals the final apply for the sampling commands' internal resets only.
Worth a sentence in the handbook and, perhaps, a `-persist` that writes the `alter`
values into the deck text.

**O4 — `-maximize` under a scalar method** prints the usage line and nothing else; the
negation NSGA-II applies could serve every method.

**O5 — knob names are not validated** before the search: `-param R9 ...` on a deck with
no `R9` runs three evaluations, prints `alter`'s error for two of them (the third is
silenced) and ends with E-499's NOTE. A dry `alter`/`altermod`/`alterparam` of the init
value before the search would refuse the name at once.

**O6 — the Pareto front is printed, not published.** `pareto1..M` carry the objective
columns; the parameter values of each front member appear on the console only. A
`pareto_<name>` vector per knob would make the front usable from a script.

**O7 — no history.** Nothing records the cost against the evaluation count, so a run's
convergence cannot be plotted or compared; `optimize_cost`, `optimize_evals`,
`optimize_status` (F1) and an optional `-trace` that fills `optimize_hist_cost` and
`optimize_hist_<name>` would close that.

**O8 — the handbook** mentions `optimize` eight times in `03-ngspice-workflows.md`, all
in the sampling and journaling sections; the command's syntax, methods and knob kinds live
in the source header, `help optimize` and eleven enhancement write-ups. A section of its
own is due.

## Verified clean

Init exactly on a bound; a negative target value (`-0.9` is not a flag); `-mparam` on a
built-in diode model (the suite's check 17); two `optimize` commands in one control block
(no state carried over — the second run's poor result was O1, reproduced alone); the
published `optimize_@r2[resistance]` vector is readable by `print` and `let`; DE with a
population below four is raised to five (F2 notes the silence); the interrupt and the
osdimc hold from E-536/E-537 were not re-tested.
