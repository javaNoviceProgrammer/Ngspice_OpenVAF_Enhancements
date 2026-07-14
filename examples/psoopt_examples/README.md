# Particle swarm optimization — `optimize -method pso` (Enhancement-194)

The built-in [`optimize`](../optimize_examples/) command (Enhancement-130/143/144/145)
had two search methods, both **local**:

- **Nelder-Mead** simplex (`-method nm`) — derivative-free, on a scalar `-minimize`;
- **Levenberg-Marquardt** (`-method lm`) — gradient least-squares over `-target`s.

Both descend into whichever basin the start point sits in. E-194 adds a third,
**global** method — **particle swarm optimization** (`-method pso`):

```
optimize -param R1 1k 10 100k -analysis op -minimize (v(out)-0.3)^2 -method pso
```

A swarm of `N` trial points flies through the normalized parameter box. Each
particle is pulled toward its own best-seen point (`pbest`) and the swarm's best
(`gbest`) with the standard **Clerc-Kennedy constriction** (χ = 0.72984,
φ = 2.05), velocities clamped to half the box. Because the whole swarm explores,
it finds the **global** optimum of a multimodal objective that traps a downhill
method. It works for both a scalar `-minimize` objective and `-target`
least-squares (unlike `-method lm`, which needs targets).

- `-swarmsize <N>` — population (default auto, ≈ `10 + 4·np`, capped at 60).
- `-seed <s>` — makes a run reproducible (PSO uses a small self-contained PRNG,
  independent of ngspice's global RNG).
- `-maxiter <N>`, `-tol <T>` — iteration cap and the gbest-stagnation tolerance.

## Why it matters

On the multimodal test function `f(p) = sin(p) + sin(10p/3)` over `[2.7, 7.5]`
(global min `p* = 5.1457`, `f* = -1.8996`; several higher local minima), started
at the `p = 2.7` corner:

```
Nelder-Mead:     converged, objective = -1.19992   p = 3.3873   <- local minimum
Particle swarm:  converged, objective = -1.8996     p = 5.1454   <- GLOBAL minimum
```

NM falls into the nearest local basin; PSO finds the global one.

## Verification

`verify_psoopt.py` — 6 checks: PSO finds the global optimum from the trapping
corner; Nelder-Mead from the same start is trapped in a higher local minimum (the
whole point); a fixed `-seed` is reproducible; several independent seeds all reach
the global basin; PSO also minimizes a `-target` least-squares objective; and PSO
solves a 2-D separable multimodal min (`f* = -3.799`). Front-end and
solver-independent, so it runs once.

## Running

```sh
python3 verify_psoopt.py
ngspice -b psoopt_demo.cir
```
