# Differential evolution — `optimize -method de` (Enhancement-195)

[Enhancement-194](../psoopt_examples/) added particle swarm (`-method pso`) as the
built-in [`optimize`](../optimize_examples/) command's first **global** method.
E-195 adds the other workhorse global optimizer: **differential evolution**
(`-method de`).

```
optimize -param R1 1k 10 100k -analysis op -minimize (v(out)-0.3)^2 -method de
```

Where particle swarm pulls trial points toward remembered bests, DE builds each
trial from a scaled **difference** of random population members and crosses it with
the target:

```
v = a + F·(b − c)                        F = 0.8   (a, b, c distinct random members)
u[j] = v[j]  if rand < CR or j = jrand, else x[i][j]     CR = 0.9  (binomial crossover)
keep u in place of x[i] if cost(u) ≤ cost(x[i])          (greedy selection)
```

The difference vector `b − c` **self-scales to the population's own spread** — large
while members are far apart, shrinking as they converge — so DE adapts its step
size automatically and is robust on rugged, discontinuous, or poorly-scaled
landscapes. It works for both a scalar `-minimize` objective and `-target`
least-squares. It shares the population/seeding options with PSO:

- `-swarmsize <N>` — population (default auto, ≈ `10 + 4·np`, capped at 60; ≥ 5,
  since DE needs at least four distinct members to form a mutant).
- `-seed <s>` — reproducible (the same self-contained splitmix64 PRNG as PSO).
- `-maxiter`, `-tol` — generation cap and the gbest-stagnation tolerance.

## Why it matters — and DE vs PSO

On the multimodal `f(p) = sin(p) + sin(10p/3)` over `[2.7, 7.5]` (global
`p* = 5.1457`, `f* = -1.8996`) started at the trapping `p = 2.7` corner:

```
Nelder-Mead:            objective = -1.19992   p = 3.3873   <- local minimum
Differential evolution: objective = -1.8996     p = 5.1457   <- GLOBAL minimum
Particle swarm:         objective = -1.8996     p = 5.1454   <- GLOBAL minimum
```

Both global methods find the global optimum where the local simplex fails. They
now form a complementary global toolbox: PSO's momentum-driven swarm and DE's
self-scaling difference vectors suit different landscapes, so having both lets you
switch strategy without leaving `optimize`.

## Verification

`verify_deopt.py` — 7 checks: DE finds the global optimum from the trapping corner;
Nelder-Mead from the same start is trapped in a higher local minimum; a fixed
`-seed` is reproducible; several seeds all reach the global basin; DE also
minimizes a `-target` least-squares objective (recovers the parameter to a 1e-13
residual); DE solves a 2-D separable multimodal min; and DE and PSO agree on the
global while the local NM does not. Front-end / solver-independent, so it runs once.

## Running

```sh
python3 verify_deopt.py
ngspice -b deopt_demo.cir
```
