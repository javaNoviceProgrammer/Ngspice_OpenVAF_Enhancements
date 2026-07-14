# Enhancement-195 — Differential evolution (`optimize -method de`)

A second global method for the built-in [`optimize`](Enhancement-130.md) command. [Enhancement-194](Enhancement-194.md) added particle swarm (`-method pso`) as the optimizer's first **global**, population-based, derivative-free search. E-195 adds the other workhorse of that family: **differential evolution** (`-method de`).

## The method

DE keeps a population of `NP` vectors in the normalized `[0,1]^np` box. Where PSO pulls trial points toward remembered best positions, DE (the classic **DE/rand/1/bin**) builds each trial from a scaled **difference** of random members and crosses it with the target:

```
v      = a + F·(b − c)                       F = 0.8   (a, b, c distinct, ≠ i)
u[j]   = v[j]  if rand < CR or j = jrand,     CR = 0.9  (binomial crossover;
         else x[i][j]                                    one dim always taken)
keep u in place of x[i]  iff  cost(u) ≤ cost(x[i])       (greedy selection)
```

with the well-tested defaults `F = 0.8`, `CR = 0.9`, positions clamped to `[0,1]`. The difference vector `b − c` **self-scales to the population's own spread**: large while the members are far apart (broad exploration), shrinking automatically as they converge (fine local refinement). That self-scaling is what makes DE robust on rugged, discontinuous, or poorly-scaled landscapes without any per-problem step tuning. It reuses the existing `opt_eval`, so it works for a scalar `-minimize` objective **and** for `-target` least-squares, like PSO.

DE shares all of PSO's infrastructure — the same self-contained splitmix64 PRNG (so `-seed` is byte-reproducible), the same `-swarmsize` population option (default auto `10 + 4·np`, capped at 60; clamped to ≥ 5 because DE needs at least four distinct members to form a mutant), and the shared `-maxiter` / `-tol` (gbest-stagnation). The `nm` / `lm` / `pso` dispatch is unchanged; DE is selected only by `-method de`.

## Why it matters — DE vs PSO

On the multimodal `f(p) = sin(p) + sin(10 p / 3)` over `[2.7, 7.5]` (global `p* = 5.1457`, `f* = -1.8996`; higher local minima) started at the trapping `p = 2.7` corner:

```
Nelder-Mead:            objective = -1.19992   p = 3.3873   (local minimum)
Differential evolution: objective = -1.8996     p = 5.1457   (GLOBAL minimum)
Particle swarm:         objective = -1.8996     p = 5.1454   (GLOBAL minimum)
```

Both global methods find the global optimum where the local simplex fails. They are complementary — PSO's momentum-driven swarm and DE's self-scaling difference vectors behave differently on different landscapes — so `optimize` now offers a small global toolbox (`pso`, `de`) alongside the local `nm` and gradient `lm`.

## Verification

[`examples/deopt_examples/verify_deopt.py`](../examples/deopt_examples/verify_deopt.py) — 7 checks: DE finds the global optimum from the trapping corner; Nelder-Mead from the same start is trapped in a higher local minimum; a fixed `-seed` is exactly reproducible; several independent seeds all reach the global basin; DE minimizes a `-target` least-squares objective (recovers the parameter to a 1e-13 residual); DE solves a 2-D separable multimodal minimum (`f* = -3.799`); and DE and PSO both reach the global while the local NM does not. The existing `optimize` (20 checks) and `psoopt` (6 checks) examples are unchanged. It is a front-end command, independent of the linear solver, so it runs once. Full example regression: 159/159.
