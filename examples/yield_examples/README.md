# yield_examples — process/mismatch correlations + Monte Carlo yield (Enhancement-151)

Two related pieces that complete the statistical flow:

1. **Native process/mismatch correlations** — `mccorr` + `mvnorm()`, so random
   `.param`s can be **correlated** (a shared process factor, a mismatch
   covariance, an arbitrary correlation matrix) instead of only independent.
2. **A packaged yield command** — `montecarlo`, which runs the Monte Carlo,
   applies pass/fail specs, and reports the **yield** with a confidence interval.

## Correlations — `mccorr` + `mvnorm`

Plain ngspice Monte Carlo draws every `agauss`/`gauss` independently, so matched
devices can't be modelled — yet whether two devices' variation is correlated is
often what decides the yield. `mccorr` registers a `k × k` correlation matrix
(Cholesky-factored once), and `mvnorm(i)` returns the `i`-th component of one
correlated standard-normal draw per Monte Carlo sample:

```
mccorr 2  1 0.9  0.9 1                 ; 90% correlation between two factors
.param r1 = 1000 + 50*mvnorm(1)        ; r1, r2 now vary together
.param r2 = 1000 + 50*mvnorm(2)
```

`mvnorm(i)` inherits the active sampler: it composes with Latin-Hypercube
(Enhancement-149) and scaled-sigma importance sampling (Enhancement-150)
automatically, and with no matrix registered it simply draws independently. The
common process + local mismatch model is the special case
`p = sigma_proc*mvnorm(shared) + sigma_mm*agauss(...)`.

## Yield — `montecarlo`

```
montecarlo <N> [-lhs] [-seed <s>] [-analysis <cmd>]
           (-spec <metric> [-max <hi>] [-min <lo>])...
```

Runs `N` samples; a sample **passes** only if *every* spec's metric is within its
`-max`/`-min` limits. Reports the yield (fraction passing) with a **Wilson 95%
confidence interval** and a per-spec violation count, and leaves
`montecarlo_yield`, `montecarlo_npass`, `montecarlo_n` for scripting. `-lhs`
draws Latin-Hypercube samples for a much lower-variance yield estimate.

- **Process corners** are the ordinary `.lib`/`.include` corner selection — load a
  corner model set, then run `montecarlo` at that corner. Correlations and corners
  compose: run the yield MC at each corner.

## Files

- **`yield_demo.cir`** — a matched resistor divider with a ±4% ratio spec; the
  same devices give **~100% yield when process-correlated (ρ=0.9)** but only
  **~74% when independent (ρ=0)** — the correlation model is what decides it.
  Run with `ngspice -b yield_demo.cir`.
- **`verify_yield.py`** — validation against analytic ground truth (Sparse-only —
  a heavy, thousands-of-re-sources deck):
  1. an `mccorr` ρ=+0.7 / −0.6 matrix reproduces the target correlation, means,
     and sigmas;
  2. `mvnorm` without a matrix draws independently;
  3. a non-positive-definite matrix is rejected;
  4. single two-sided spec yield matches `P(|Z| < k)`;
  5. two independent specs' yields multiply;
  6. `-lhs` is unbiased and much lower-variance;
  7. positive parameter correlation raises the joint yield.

```
python3 verify_yield.py
```

## Notes

- `mvnorm(i)` returns a **unit-variance** standard normal; scale it in the
  `.param` (`nom + sigma*mvnorm(i)`). The `mccorr` matrix is a **correlation**
  matrix (unit diagonal).
- Correlations and yield are front-end features (they change only which parameter
  values are drawn), so they are solver-independent; the verify is a heavy deck
  and runs under Sparse only.
- Every SPICE deck's first line is the **title** (ignored by the parser); the
  decks here start with a `*` title line accordingly.
