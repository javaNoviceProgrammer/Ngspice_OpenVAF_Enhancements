# Enhancement-196 — Simulated annealing (`optimize -method sa`)

A third global method for the built-in [`optimize`](Enhancement-130.md) command, completing the search-method set. [Enhancement-194](Enhancement-194.md) (particle swarm) and [Enhancement-195](Enhancement-195.md) (differential evolution) added two *population-based* global optimizers. E-196 adds the classic *single-walker* one: **simulated annealing** (`-method sa`).

## The method

SA holds a single current point in the normalized `[0,1]^np` box. Each step it proposes a random neighbour `xn = clamp01(x + step·U(-1,1))` and applies the **Metropolis** acceptance rule:

- accept if `cost(xn) ≤ cost(x)` (a downhill move), or
- accept anyway with probability `exp(-(cost(xn) - cost(x)) / T)` (an uphill move).

While the **temperature `T`** is high, uphill moves are readily accepted, so the walker climbs out of local minima; `T` is then **cooled geometrically** (`T ← α·T`, α set so `T` drops ~4 decades over the run), so uphill moves become rare and the walker settles into a minimum. The best point ever visited is returned. It evaluates **one** candidate per step — no population — which makes it the lightest-weight global method, and the natural choice when each analysis is expensive and you want a global search without a whole population of simultaneous evaluations.

Everything is auto-scaled to the problem: the **initial temperature** `T0` is the mean `|Δcost|` of a handful of random probes (so an uphill move of that size is accepted about half the time when hot), and the **step size** shrinks as `T` cools (wide exploration when hot, fine refinement when cold). There is nothing to tune. It reuses the existing `opt_eval`, so it works for a scalar `-minimize` objective and for `-target` least-squares. `-seed <s>` makes a run reproducible (the same self-contained splitmix64 PRNG as PSO/DE); `-maxiter` is the number of cooling levels. The `nm`/`lm`/`pso`/`de` dispatch is unchanged.

## Why it matters — the complete toolbox

On the multimodal `f(p) = sin(p) + sin(10 p / 3)` over `[2.7, 7.5]` (global `p* = 5.1457`, `f* = -1.8996`) started at the trapping `p = 2.7` corner, all five methods:

```
Nelder-Mead (local):             objective = -1.19992   p = 3.3873   (local minimum)
Simulated annealing (global):    objective = -1.8996     p = 5.1458   (GLOBAL)
Particle swarm (global):         objective = -1.8996     p = 5.1454   (GLOBAL)
Differential evolution (global): objective = -1.8996     p = 5.1457   (GLOBAL)
```

`optimize` now spans local descent (`nm`, `lm`) and three complementary global strategies (`pso`, `de`, `sa`). A single walker refines a little more loosely than a population, so SA reliably reaches the global **basin** rather than machine precision; a short `nm`/`lm` polish from its result sharpens it when that matters.

## Verification

[`examples/saopt_examples/verify_saopt.py`](../examples/saopt_examples/verify_saopt.py) — 7 checks: SA finds the global basin from the trapping corner; Nelder-Mead from the same start is trapped in a higher local minimum; a fixed `-seed` is reproducible; several independent seeds all reach the global basin; SA minimizes a `-target` least-squares objective; SA solves a 2-D separable multimodal minimum; and all three global methods (sa/pso/de) reach the global while the local nm does not. The existing `optimize` (20), `psoopt` (6) and `deopt` (7) examples are unchanged. It is a front-end command, independent of the linear solver, so it runs once. Full example regression: 160/160.
