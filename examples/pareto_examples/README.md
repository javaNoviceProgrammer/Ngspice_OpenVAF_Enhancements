# pareto_examples — Enhancement-216: NSGA-II multi-objective / Pareto optimization

`optimize -method nsga2` trades **competing** objectives and returns a **Pareto
front** of non-dominated designs, rather than the single optimum the scalar methods
return ([E-130](../../enhancements_doc/Enhancement-130.md) Nelder-Mead,
[E-194](../../enhancements_doc/Enhancement-194.md) PSO,
[E-195](../../enhancements_doc/Enhancement-195.md) DE,
[E-196](../../enhancements_doc/Enhancement-196.md) SA). It is the multi-objective
generalization of [E-206](../../enhancements_doc/Enhancement-206.md) design
centering — real design problems trade gain against bandwidth, power against speed,
area against yield, and there is no single "best".

```
optimize -dparam px 1 -1 3 -analysis op \
         -minimize v(f1) -minimize v(f2) -method nsga2
```

Give **two or more** objectives with `-minimize <expr>` / `-maximize <expr>`; the
command reports the front and publishes each objective column as a vector
`pareto1`, `pareto2`, … so it can be plotted (`plot pareto2 vs pareto1`).

## The algorithm

Standard NSGA-II (Deb et al.): a real-coded genetic algorithm over the normalized
parameters, with **fast non-dominated sorting** (Pareto rank), **crowding distance**
(spread along the front), binary-tournament selection by the crowded-comparison
operator, **SBX** crossover and **polynomial** mutation, and elitist
(parent+offspring) survivor selection.

## The demo

`pareto_demo.cir` is the Schaffer-1 benchmark: over one knob `px ∈ [-1, 3]`,
minimize `f1 = px²` and `f2 = (px-2)²` at once. These conflict, so the answer is a
curve — the Pareto set is exactly `px ∈ [0, 2]`, and in objective space the front is
`f2 = (√f1 - 2)²`. NSGA-II must discover that `[0, 2]` sub-range and spread points
along it.

## What is verified

`verify_pareto.py` (6 checks, both solvers):
1. the run returns a front of a reasonable number of points;
2. every point is genuinely **non-dominated**;
3. the published front lies on the analytic curve to **machine precision** (8.9e-16),
   and the printed front matches `f1=px²`, `f2=(px-2)²` at display precision;
4. the front **spans** the trade-off (`px` reaches near 0 and near 2).

## Run

```sh
python3 verify_pareto.py
```
