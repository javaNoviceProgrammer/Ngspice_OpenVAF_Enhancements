# Simulated annealing — `optimize -method sa` (Enhancement-196)

Enhancements [194](../psoopt_examples/) and [195](../deopt_examples/) added two
*population-based* global methods (particle swarm, differential evolution) to the
built-in [`optimize`](../optimize_examples/) command. E-196 adds the classic
*single-walker* global optimizer: **simulated annealing** (`-method sa`).

```
optimize -param R1 1k 10 100k -analysis op -minimize (v(out)-0.3)^2 -method sa
```

From the current point, SA proposes a random neighbour and:

- **accepts it if it is better**, or
- **accepts it if it is worse with probability `exp(-Δcost / T)`** — the Metropolis
  rule.

So while the **temperature `T`** is high it readily climbs *uphill*, escaping local
minima; as `T` is **cooled geometrically toward zero** it accepts fewer uphill
moves and settles into a minimum. It evaluates **one** candidate per step (no
population), which makes it the lightest-weight global method — attractive when
each analysis is expensive. The initial temperature (from the cost spread of a few
random probes) and the step size (which shrinks as `T` cools) are auto-scaled to
the problem, so there is nothing to tune. `-seed <s>` makes a run reproducible.

## Why it matters, and the complete toolbox

On the multimodal `f(p) = sin(p) + sin(10p/3)` over `[2.7, 7.5]` (global
`p* = 5.1457`, `f* = -1.8996`) started at the trapping `p = 2.7` corner, all five
`optimize` methods:

```
Nelder-Mead (local):            objective = -1.19992   p = 3.3873   <- local minimum
Simulated annealing (global):   objective = -1.8996     p = 5.1458   <- GLOBAL
Particle swarm (global):        objective = -1.8996     p = 5.1454   <- GLOBAL
Differential evolution (global):objective = -1.8996     p = 5.1457   <- GLOBAL
```

`optimize` now offers a full spread of strategies:

| Method | Kind | Character |
|---|---|---|
| `nm` | local, derivative-free | downhill simplex |
| `lm` | local, gradient least-squares | curve fitting / extraction |
| `pso` | **global**, population | momentum-driven swarm |
| `de` | **global**, population | self-scaling difference vectors |
| `sa` | **global**, single walker | temperature-controlled explore→exploit |

A single walker refines a little more loosely than a population, so SA lands in the
global *basin* rather than to machine precision; a short `nm`/`lm` polish from its
result sharpens it if needed.

## Verification

`verify_saopt.py` — 7 checks: SA finds the global basin from the trapping corner;
Nelder-Mead from the same start is trapped in a higher local minimum; a fixed
`-seed` is reproducible; several seeds all reach the global basin; SA also
minimizes a `-target` least-squares objective; SA solves a 2-D multimodal minimum;
and all three global methods (sa/pso/de) reach the global while the local nm does
not. Front-end / solver-independent, so it runs once.

## Running

```sh
python3 verify_saopt.py
ngspice -b saopt_demo.cir
```
