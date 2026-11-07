# Enhancement-918: a design that failed is no part of a Pareto front — under `-maximize` it led one — and a front of maxima alone is accepted

**Scope:** F5 of the [`optimize` hunt of 2026-09-29](../docs/bug_hunts/2026-09-29_optimize-command.md),
which also turned out worse than that hunt saw.

ngspice:
- `frontend/com_optimize.c` (`opt_eval_objs`, `nsga2`, the command's validation).

**ngspice only.**

**Suites:**
- [`pareto_examples`](../examples/pareto_examples/): 30 checks per solver, 13 of which fail on E-917.
- `optimize` 73, `optmethods` 97, `helpcmd` 27 and the other suites that run `optimize`: unchanged.
- The full sweep was not run.

## What was wrong

`opt_eval_objs` read each objective, set a failure to `1e15`, and only then negated the maximized
ones:

```c
if (v >= OPT_PENALTY)
    v = 1e15;                       /* failed eval -> dominated everywhere */
f[i] = c->obj_max[i] ? -v : v;      /* minimization convention */
```

Four faults came from that, all on the front the user reads:

| fault | deck | on E-917 |
|---|---|---|
| A failure under `-maximize` becomes `-1e15`, the best value there is | a solve with no solution for `0 < Vx < 1`, `-maximize v(x) -minimize v(x)+v(out)` | 2 of 12 designs on the front are failures, printed `1e+15 1e+15` |
| The same, when the other objective also favours the failing region | `-maximize log(v(out)-0.4) -minimize abs(i(v1))`, unreadable for `R1 > 1.5k` | **16 of 16** designs are failures, all `R1 = 10k` |
| One objective failed and the others not: the design keeps their values, so it is not dominated, under `-minimize` too | `-minimize 0-log(v(out)-0.4) -minimize abs(i(v1))` | 2 of 16 designs read `1e+15` |
| The analysis's failure is not asked about (F5): what it left standing is read as this design's | `@n1[g]` of a model refusing `g <= 0` | `g = -0.00111304` on the front with its neighbour's objectives, as the hunt saw it |

The second row is the worst: the search converges on what failed and returns nothing usable. The
comment was right about what was meant and wrong about what happened.

A fifth, nearby: a front of `-maximize` objectives alone printed the usage line. Only `-minimize`
set `c.objective`, the scalar methods' objective, and the validation asked for that, although
the help says each objective may be either.

## What changed

A design that did not solve (`opt_run_failed()`, as `opt_eval` has had since E-438) or has an
objective that cannot be read is **worst in every objective**: `OPT_PENALTY`, after the sign, and
counted in `nfailed`. It is dominated by every design that solved, so the failures sink to the last
rank, and they have a rank of their own, so they do not stretch the crowding distance of the
designs that count.

`1e15` is gone with it: a real objective can pass it (a frequency), and would then have lost to a
failure. `OPT_PENALTY` is what `opt_eval_expr` already calls a failure.

The front leaves out what failed. With no design that solved, the failures are the first rank: the
front is empty, `optimize_status` is `nosolve` (or `interrupted`, if that is why), and
`optimize_converged` is 0. E-438's NOTE is printed under `nsga2`, which it had never reached:

```
optimize: NSGA-II Pareto front -- 12 non-dominated designs after 84 evaluations
optimize: NOTE -- 12 of 84 evaluations did not solve or had an objective that could not be read, and are no part of the front; check that the search range stays inside every parameter's legal domain.
```

Under `nsga2`, any objective now satisfies the validation. One `-maximize` under a scalar method is
still refused with the usage line (O4 of the hunt).

## Results

| objectives | E-917 | E-918 |
|---|---|---|
| `-maximize v(x) -minimize v(x)+v(out)` | 2 of 12 failed | 0 of 12; "12 of 84" said |
| `-maximize log(v(out)-0.4) -minimize abs(i(v1))` | 16 of 16 failed | 0 of 16, `R1` from 100 to 1.5k; "54 of 144" said |
| the same as `-minimize 0-log(...)` | 2 of 16 failed | 0 of 16, the same designs as the row above |
| `@n1[g]` refused at `g <= 0` | `g = -0.00111304` on the front | none at `g <= 0`; said |
| nothing readable | 16 rows of `1e+15`, `completed` | no rows, `nosolve` |
| `-maximize v(x) -maximize 5-v(out)` | usage | a front |

## Not done

F5 also asked for `opt_reuse_ask()` on this path, so that NSGA-II stops rebuilding the circuit at
each evaluation. That is speed, not correctness, and is left open.

The `optimize` and `optmethods` suites fail in a checkout whose path holds a space, with or without
this change: `pre_osdi` splits the path. They were run from a copy at a path with none.
