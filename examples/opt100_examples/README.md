# A 100-parameter circuit optimization — raised `optimize` limits (Enhancement-197)

The built-in [`optimize`](../optimize_examples/) command — extended with
least-squares curve fitting ([143–145](../optimize_examples/)) and three global
search methods, [particle swarm](../psoopt_examples/) (194),
[differential evolution](../deopt_examples/) (195) and
[simulated annealing](../saopt_examples/) (196) — previously capped a run at **16
parameters** and **64 targets**. E-197 raises those to **128 each** (and the
auto-population cap from 60 to 256), so a genuinely large problem can be
optimized in a single call.

## Testbed: 100 unknowns

100 independent 1 mA current sources, each driving an unknown resistor `R_i` to
ground, so `v(n_i) = 1e-3 · R_i`. The 100 targets

```
t_i = 1e-3 · (100 + 9800·i/99) ohm      (a linear ramp 0.1 V .. 9.9 V)
```

make a well-posed, separable **100-dimensional least-squares** fit.

```
optimize -param R0 1k 10 10000  -param R1 1k 10 10000  ...  (100 of these)
         -analysis op  -target v(n0) 0.1  -target v(n50) 5.04949 ... (100 of these)
         -method lm
```

## What happens

**Levenberg-Marquardt nails it.** For a well-posed high-dimensional fit, the
gradient least-squares solver is the right tool: it recovers all 100 resistors to
**machine precision** in about two seconds —

```
optimize: converged, sum-sq residual = 2.5e-29 (rms 5.0e-16) after 619 evaluations
v(n0) = 0.100000   v(n50) = 5.049490   v(n99) = 9.900000     (targets hit exactly)
```

**The global methods now function at scale, too.** Differential evolution is a
*global*, population search — it does not use derivatives, so at 100 dimensions it
is intrinsically much slower than LM, but E-197 makes it *work* at that scale. The
key fix is an **adaptive crossover rate**: classic DE (`CR = 0.9`) mutates almost
every coordinate of a trial vector, and in high dimension a trial that perturbs
~100 coordinates at once is essentially always worse than its parent and gets
rejected — so DE freezes at its starting guess. E-197 caps the expected number of
mutated coordinates at ~15 for large problems, and DE descends again:

```
DE at 100-D:   start 1240  ->  882 after a short search   (was frozen before the fix)
```

DE will not fully converge a 100-D *global* search in a short budget — that cost
is intrinsic to global optimization in high dimension, not a defect. The message
is the division of labor: **LM** solves a well-posed high-dimensional fit exactly
and fast; the **global** methods (`pso`/`de`/`sa`) are for multimodal problems and
now remain usable as the dimension grows.

## Which method for 100 unknowns?

| Situation | Method | Why |
|---|---|---|
| Well-posed fit / extraction (a unique best fit) | `lm` | gradient least-squares → machine precision, ~10²–10³ evals |
| Smooth, unimodal, no good gradient | `nm` | derivative-free downhill simplex |
| Multimodal / many local minima | `pso` / `de` / `sa` | global search; expensive but robust in high-D with E-197's fixes |

## Verification

`verify_opt100.py` — 4 checks: LM fits all 100 parameters to 100 targets at
machine precision (proving both raised caps at once); DE descends substantially at
100-D (the adaptive high-dimensional crossover); a fixed `-seed` is reproducible
even at 100 dimensions; and exceeding the raised cap (129 params) is reported
cleanly rather than crashing. The existing `optimize` (39), `psoopt` (6), `deopt`
(7) and `saopt` (7) examples are unchanged. Front-end command, independent of the
linear solver, so it runs once.

## Running

```sh
python3 verify_opt100.py
ngspice -b opt100_demo.cir
```
