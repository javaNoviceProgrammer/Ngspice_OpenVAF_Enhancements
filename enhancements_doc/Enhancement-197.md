# Enhancement-197 — A 100-parameter circuit optimization (raised `optimize` limits)

The built-in [`optimize`](Enhancement-130.md) command — extended with
Levenberg-Marquardt least-squares fitting ([143](Enhancement-143.md)–[145](Enhancement-145.md))
and three global search methods, particle swarm ([194](Enhancement-194.md)),
differential evolution ([195](Enhancement-195.md)) and simulated annealing
([196](Enhancement-196.md)) — carried compile-time limits of **16 parameters** and
**64 least-squares targets**. E-197 raises those to **128 each** (and the
auto-population cap from 60 to 256), and fixes what breaks when the global methods
are actually run at that scale, so a genuinely large problem can be optimized in a
single call.

## Raised limits

`com_optimize.c` sizes its per-run arrays from two macros, now:

```c
#define OPT_MAXP    128   /* max parameters to optimize  (was 16) */
#define OPT_MAXT    128   /* max least-squares targets    (was 64) */
```

Those bound the `-param`/`-mparam`/`-dparam` knob arrays and the LM Jacobian
`J[OPT_MAXT][OPT_MAXP]`, so raising them costs a little stack per run and nothing
else. The auto-population sizing for the population methods (PSO/DE), previously
capped at 60, now caps at 256 so a high-dimensional run gets an adequately sized
swarm (`-swarmsize` still overrides). Exceeding a cap is reported cleanly
(`optimize: too many -param (max 128)`), not crashed.

## Testbed: 100 unknowns

100 independent 1 mA current sources, each driving an unknown resistor `R_i` to
ground, so `v(n_i) = 1e-3 · R_i`. The 100 targets `t_i = 1e-3 · (100 + 9800·i/99)`
ohm form a linear voltage ramp 0.1 V … 9.9 V — a well-posed, separable
**100-dimensional least-squares**.

**Levenberg-Marquardt solves it to machine precision.** For a well-posed
high-dimensional fit, the gradient least-squares solver is the right tool:

```
optimize: converged, sum-sq residual = 2.5e-29 (rms 5.0e-16) after 619 evaluations
v(n0) = 0.100000   v(n50) = 5.049490   v(n99) = 9.900000     (targets hit exactly)
```

all 100 parameters and 100 targets accepted and honored, in about two seconds.

## Making the global methods work at scale

The global methods are derivative-free, so at 100 dimensions they are intrinsically
far slower than LM — but two changes were needed to make them *function* at that
scale rather than stall.

**Adaptive crossover for DE.** Classic DE/rand/1/bin uses a crossover rate
`CR = 0.9`, which mutates almost every coordinate of a trial vector. In high
dimension a trial that perturbs ~`n` coordinates at once is essentially always
worse than its parent and gets rejected by greedy selection — so DE freezes at its
starting guess (observed: gbest flat at the initial cost, zero progress). E-197
caps the *expected number of mutated coordinates* at ~15 for large problems:

```c
const double CR = (n <= 16) ? 0.9 : 15.0 / (double) n;
```

For `n ≤ 16` this is exactly the classic `CR = 0.9`, so the existing low-dimensional
DE behavior (and its example) is unchanged; for `n = 100` it is `CR = 0.15`, and DE
descends again — from ~1240 to ~882 over 35 generations on the testbed.

**Dimension-scaled convergence patience.** High-dimensional population runs plateau
for several generations between improvements, so the stagnation counter that stops
PSO/DE on convergence would otherwise cut a still-descending high-D run short. The
threshold now grows with dimension:

```c
if (++stall >= 8 + n / 4) break;   /* was: >= 8 */
```

For `n ≤ 3` this is exactly the previous `8`, so the small-`n` tests are unchanged;
at `n = 100` it gives 33 generations of patience.

## Which method for many unknowns

DE at 100-D is a genuinely hard *global* search and does not fully converge in a
short budget — that cost is intrinsic to global optimization in high dimension, not
a defect. The division of labor is the point:

| Situation | Method |
|---|---|
| Well-posed fit / extraction (unique best fit) | `lm` — machine precision, ~10²–10³ evals |
| Smooth, unimodal, no gradient | `nm` — derivative-free simplex |
| Multimodal / many local minima | `pso` / `de` / `sa` — global; now usable as dimension grows |

## Verification

[`examples/opt100_examples/verify_opt100.py`](../examples/opt100_examples/verify_opt100.py)
— 4 checks: LM fits all 100 parameters to 100 targets at machine precision (proving
both raised caps at once); DE descends substantially at 100-D (self-calibrated
against its own starting cost, ≥ 15% reduction — the adaptive high-dimensional
crossover); a fixed `-seed` is bit-reproducible even at 100 dimensions; and
exceeding the raised cap (129 params) is reported cleanly rather than crashing. The
existing `optimize` (39), `psoopt` (6), `deopt` (7) and `saopt` (7) examples are
unchanged. It is a front-end command, independent of the linear solver, so it runs
once. Full example regression: 161/161.
