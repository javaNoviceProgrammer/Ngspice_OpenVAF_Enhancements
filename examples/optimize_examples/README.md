# optimize_examples — the built-in `optimize` command (Enhancements 130, 143, 144, 145, 322, 323, 762, 763)

```
python3 verify_optimize.py
```

69 checks, one solver (a front-end command; the linear solver does not enter). 47 of 69 on
the E-761 binary, 68 of 69 on the E-763 binary (the bare `-method` message names `cmaes` since
[Enhancement-764](../../enhancements_doc/Enhancement-764.md)).

Sections [1]–[18] are the command's original coverage: analytic optima reached by
Nelder-Mead and Levenberg-Marquardt over instance, `.model` and `.param` knobs, single and
multi-stage least-squares fits, a compiled diode's parameter extraction, input validation,
the quiet inner analyses, the `.param` fast path.

Section [19] is Enhancement-762 (F1 of the 2026-09-29 optimize hunt): the stop status.
Every stop used to be reported as "converged" — the iteration cap, a run in which no
evaluation solved, one whose objective never moved — and only an interrupt was told
apart. The methods now record why they stopped and the report opens with it:

| stop | line | `optimize_status` | `optimize_converged` |
|---|---|---|---|
| the method's criterion | `converged, ...` (unchanged) | `converged` | 1 |
| `-maxiter` ran out | `stopped at -maxiter (N iterations) -- NOT converged, ...` and a NOTE to raise it | `maxiter` | 0 |
| a fixed schedule ended (sa, nsga2) | `cooling schedule complete (N levels), ...` | `completed` | 1 |
| no evaluation solved | `NO SOLUTION -- no evaluation solved, ...` | `nosolve` | 0 |
| the objective never moved | `unchanged -- nothing was optimised, ...` | `unchanged` | 0 |
| the user interrupted | `INTERRUPTED -- best point so far, ...` | `interrupted` | 0 |

`optimize_cost` and `optimize_evals` are published beside them (vectors and shell
variables), equal to the numbers on the line.

Section [20] is Enhancement-763 (F2 and F3 of the same hunt): the parser refuses what it
cannot mean instead of running with a guess. A bound that is not a number (`abc` was 0),
an init outside `[lo, hi]` (it was clamped), a zero or negative weight, a `-target`
expression with spaces (it fitted to a target of 0), a bare `-method` or `-maxiter`, two
`-minimize` under a scalar method, a knob given twice and a stray token each print a
message and no run follows; SPICE suffixes, a negative target value and a raised
population (with a NOTE) still work; `-minimize -v(out)` is refused with the quoting hint
and `-minimize "-v(out)"` runs.
