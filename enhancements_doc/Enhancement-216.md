# Enhancement-216 — NSGA-II multi-objective / Pareto optimization

Real design problems rarely have a single "best". A design trades **gain against
bandwidth**, **power against speed**, **area against yield** — and the honest answer
is not a point but a **Pareto front**: the set of designs where you cannot improve
one objective without giving up another. Every optimizer this project had so far
returned a single optimum: Nelder-Mead ([E-130](Enhancement-130.md)), particle
swarm ([E-194](Enhancement-194.md)), differential evolution
([E-195](Enhancement-195.md)), simulated annealing ([E-196](Enhancement-196.md)),
and the design-centering objective ([E-206](Enhancement-206.md)) all minimize one
scalar cost. E-216 adds the multi-objective generalization.

```
optimize -dparam px 1 -1 3 -analysis op \
         -minimize v(f1) -minimize v(f2) -method nsga2
```

`-method nsga2` takes **two or more** objectives — each `-minimize <expr>` or
`-maximize <expr>` — and returns the whole non-dominated front instead of one
design. It reuses the entire existing `optimize` infrastructure (the parameter
knobs, the analysis-driven expression objectives, the normalized `[0,1]` search
space and RNG); only the algorithm and the result are new.

## The algorithm

Standard **NSGA-II** (Deb, Pratap, Agarwal & Meyarivan, 2002), the reference
elitist multi-objective genetic algorithm:

- **Fast non-dominated sorting** partitions the population into Pareto fronts:
  front 0 is the non-dominated set, front 1 is what remains non-dominated once
  front 0 is removed, and so on. (`a` dominates `b` when it is no worse on every
  objective and strictly better on at least one.)
- **Crowding distance** measures how isolated each member is within its front — the
  sum over objectives of the normalized gap to its two neighbours, with the two
  boundary members held at infinity. It is the diversity pressure that spreads
  points *along* the front rather than clumping them.
- **Selection** is a binary tournament by the *crowded-comparison* operator: a lower
  Pareto rank wins, ties broken by the larger crowding distance.
- **Variation** is real-coded: **simulated binary crossover** (SBX, η=15) and
  **polynomial mutation** (η=20, rate 1/n) on the normalized parameters.
- **Survivor selection is elitist**: parents and offspring (2N) are pooled, ranked
  and crowded together, and the best N carried forward — so a non-dominated design
  is never lost.

Maximized objectives are negated internally, so a single "smaller is better"
convention runs throughout; the reported front un-negates them.

## Output

The command prints the final front — each non-dominated design's objective values
and parameters, sorted by the first objective:

```
optimize: NSGA-II Pareto front -- 24 non-dominated designs after 984 evaluations
    min:v(f1) min:v(f2) | px
    1.78135e-07 3.99831 | 0.000422061
    ...
    4.00692 2.99425e-06 | 2.00173
```

Each objective column is also published as a vector `pareto1`, `pareto2`, … so the
front can be plotted directly (`plot pareto2 vs pareto1`).

## Verification (`examples/pareto_examples`)

The Schaffer-1 benchmark gives a front with a **known closed form**: over one knob
`px ∈ [-1, 3]`, minimizing `f1 = px²` and `f2 = (px-2)²` simultaneously has
Pareto-optimal set exactly `px ∈ [0, 2]`, tracing `f2 = (√f1 - 2)²` in objective
space. The knob's range is deliberately wider than the front so NSGA-II must
*discover* the `[0, 2]` sub-range. `verify_pareto.py` (6 checks, both solvers)
confirms the front is a reasonable size, **every point is non-dominated**, the
published front lies on the analytic curve to **machine precision (8.9e-16)** (the
printed front matches `f1=px²`/`f2=(px-2)²` to display precision), and it **spans**
the trade-off (`px` reaching near 0 and near 2). Full regression: 176/176.

## Scope

ngspice only, one file (`frontend/com_optimize.c`): the `nsga2` method plus a
vector-valued objective evaluator and the multi-objective `-minimize`/`-maximize`
parsing. The scalar methods and their single-objective/least-squares/centering
paths are unchanged (a lone `-minimize` still seeds the scalar objective for
nm/pso/de/sa). `-method nsga2` requires at least two objectives and a single
`-analysis` stage; population defaults to `20 + 4·np` (override with `-swarmsize`),
generations to `-maxiter`, with `-seed` for reproducibility.
