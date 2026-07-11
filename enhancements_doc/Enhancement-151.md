# Enhancement-151 — process/mismatch correlations and a packaged yield flow

[Enhancement-149](Enhancement-149.md) and [Enhancement-150](Enhancement-150.md)
made Monte Carlo efficient and gave it a rare-event tail. Two pieces of the
statistical story were still only *partial* (⚠️) versus a commercial simulator:

- **Native process/mismatch correlations.** ngspice draws every `agauss`/`gauss`
  independently — "every textual occurrence of a random `{param}` draws
  independently" (the Enhancement-66 gotcha). So *matched* devices could not be
  modelled, yet whether two devices' variation is **correlated** is often exactly
  what decides the yield.
- **A packaged corner + MC + yield flow.** Yield had to be assembled by hand from
  a `reset` loop and manual pass/fail bookkeeping.

Enhancement-151 closes both — the last two ⚠️ rows in the statistical section of
the [gap analysis](../docs/internals/ngspice_internals/ngspice_gaps.md).

## Correlations — `mccorr` + `mvnorm`

```
mccorr <k> <m11> <m12> ... <mkk>     register a k x k correlation matrix
mccorr off                           clear it
```

`mccorr` takes a `k × k` correlation matrix (row-major, symmetric, unit diagonal)
and **Cholesky-factors** it once into a lower-triangular `L`. A new `.param`
function **`mvnorm(i)`** returns the `i`-th component of one correlated
standard-normal draw per Monte Carlo sample: `y = L·z` with `z ~ N(0, I)`. So
correlated variation is expressed directly in the `.param`s:

```spice
mccorr 2  1 0.9  0.9 1                 ; rho = 0.9 between the two factors
.param r1 = 1000 + 50*mvnorm(1)        ; r1, r2 vary together
.param r2 = 1000 + 50*mvnorm(2)
```

The underlying `z`'s are drawn through the same mode-aware `mc_sample_gauss()` the
other sampling modes use, so correlations **compose** with Latin-Hypercube
(E-149) and scaled-sigma importance sampling (E-150) for free; with no matrix
registered, `mvnorm()` degrades to independent draws. The common **process +
mismatch** model is the special case `sigma_proc·mvnorm(shared) + sigma_mm·agauss(...)`.

## Yield — `montecarlo`

```
montecarlo <N> [-lhs] [-seed <s>] [-analysis <cmd>]
           (-spec <metric> [-max <hi>] [-min <lo>])...
```

Runs `N` Monte Carlo samples (each re-sources the deck and runs `-analysis`,
default `op`), evaluates every `-spec` metric, and counts a sample as **pass**
only if all specs are within their limits. It reports the **yield** with a
**Wilson 95% confidence interval** and a per-spec violation count, and leaves
`montecarlo_yield`, `montecarlo_npass`, `montecarlo_n` for scripting. `-lhs` uses
Latin-Hypercube sampling for a much lower-variance yield estimate. **Process
corners** are the ordinary `.lib`/`.include` corner selection — load a corner
model set and run `montecarlo` at that corner; correlations and corners compose.

## Implementation notes

- **Sampler** (`maths/misc/randnumb.c`): `mc_corr_config(k, matrix)` Cholesky-
  factors the correlation matrix (rejecting a non-positive-definite one);
  `mc_corr_component(i)` lazily draws the `k` underlying `z`'s once per sample
  (through `mc_sample_gauss()`, so LHS/SSS apply and SSS weights accumulate),
  applies `L`, caches `y`, and returns `y[i]`. The cache is invalidated every pass
  in `mc_sample_advance()` — which now runs its reset in **every** mode, so
  correlations work under plain MC too. `com_mccorr` parses the matrix; a reusable
  `mc_lhs_config()` was factored out of `com_mcsample` for `montecarlo -lhs`.
- **`mvnorm`** is added to the numparam expression evaluator (`numparam/xpressn.c`)
  — one entry in the function list / enum / dispatch, calling `mc_corr_component`.
- **`com_montecarlo`** lives in `frontend/com_sweep.c` (reuses its synchronous
  command runner and expression evaluator). Registered in `commands.c` with
  `mccorr`.
- Front-end only, so solver-independent.

## Verification

`examples/yield_examples/verify_yield.py` (Sparse-only — heavy deck):

- **[1]** an `mccorr` ρ=+0.7 / −0.6 matrix reproduces the empirical correlation
  (0.711 / −0.614) with the right means and sigmas.
- **[2]** `mvnorm` without a matrix draws independently (corr ≈ 0).
- **[3]** a non-positive-definite matrix is rejected.
- **[4]** single two-sided spec yield matches `P(|Z| < k)` (0.8660 vs 0.8664).
- **[5]** two independent specs' yields multiply (0.7508 vs 0.7506).
- **[6]** `-lhs` is unbiased and much lower-variance (measured ~800× lower yield-
  estimate variance at the same N).
- **[7]** positive parameter correlation raises the joint yield (0.75 → 0.82).

`yield_demo.cir` — a matched divider that yields **~100% when process-correlated
(ρ=0.9) but only ~74% when independent**: the correlation model is what decides it.

## Scope and follow-ups

Native correlated process/mismatch sampling (arbitrary correlation matrix, via
`mvnorm`) and a packaged, spec-based Monte Carlo yield command with a confidence
interval and optional Latin-Hypercube variance reduction. Follow-ups: multiple
independent correlation groups, a covariance (non-unit-diagonal) form, and a
one-command corner-sweep-of-yield wrapper.
