# Enhancement-194 — Particle swarm optimization (`optimize -method pso`)

A new search method for the built-in [`optimize`](Enhancement-130.md) command. The optimizer already had two methods, both **local**:

- **Nelder-Mead** simplex (`-method nm`, Enhancement-130) — derivative-free, on a scalar `-minimize` objective;
- **Levenberg-Marquardt** (`-method lm`, Enhancement-143) — gradient least-squares over one or more `-target`s.

Both descend into whichever basin the start point sits in, so on a **multimodal** objective — several local minima — they return whatever local minimum is nearest the start. E-194 adds a third, **global** method: **particle swarm optimization** (`-method pso`).

## The method

PSO is a population-based, derivative-free global search. `N` particles fly through the normalized `[0,1]^np` parameter box; each keeps its own best-seen point (`pbest`), and the swarm shares a global best (`gbest`). Each iteration updates every particle's velocity toward `pbest` and `gbest` and moves it:

```
v ← χ·( v + φ·r1·(pbest − x) + φ·r2·(gbest − x) )      χ = 0.72984,  φ = 2.05
x ← clamp01( x + v )                                    |v| ≤ 0.5
```

with the standard **Clerc-Kennedy constriction coefficients** (χ, φ chosen so the swarm converges without exploding), velocities clamped to half the box, and positions clamped to `[0,1]`. Particle 0 starts at the user's init point; the rest are seeded uniformly at random, so the whole box is explored. It reuses the existing `opt_eval` (which returns the scalar cost for both objective kinds), so PSO works for a scalar `-minimize` **and** for `-target` least-squares — unlike `-method lm`, which requires targets.

New options:

- `-swarmsize <N>` (aliases `-swarm`, `-npart`) — population; default auto, `10 + 4·np` capped at 60.
- `-seed <s>` — makes a run reproducible. PSO draws from a small self-contained splitmix64 PRNG, independent of ngspice's global RNG state, so a given seed gives byte-identical results.
- `-maxiter`, `-tol` are shared with the other methods (`-tol` is the gbest-stagnation tolerance, held over several iterations before stopping).

The dispatch is unchanged for the existing methods (`nm`/`lm` behave exactly as before); PSO is selected only by `-method pso`.

## Why it matters

On the classic multimodal function `f(p) = sin(p) + sin(10 p / 3)` over `[2.7, 7.5]` (global minimum `p* = 5.1457`, `f* = -1.8996`; several higher local minima), started at the `p = 2.7` corner:

```
Nelder-Mead:     converged, objective = -1.19992   p = 3.3873   (local minimum)
Particle swarm:  converged, objective = -1.8996     p = 5.1454   (GLOBAL minimum)
```

Nelder-Mead falls into the nearest local basin; PSO finds the global one. It costs more evaluations (a swarm × iterations) but does not depend on a good starting guess.

## Verification

[`examples/psoopt_examples/verify_psoopt.py`](../examples/psoopt_examples/verify_psoopt.py) — 6 checks: PSO finds the global optimum from the trapping corner start; Nelder-Mead from the *same* start is trapped in a higher local minimum (the whole point); a fixed `-seed` is exactly reproducible; several independent seeds all reach the global basin; PSO also minimizes a `-target` least-squares objective (recovers the parameter to a 1e-12 residual); and PSO solves a 2-D separable multimodal minimum (`f* = -3.799`). The existing `optimize` example (Nelder-Mead + Levenberg-Marquardt, 20 checks) continues to pass unchanged. It is a front-end command, independent of the linear solver, so it runs once. Full example regression: 158/158.
