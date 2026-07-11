# highsigma_examples — rare-event / high-sigma probability (Enhancement-150)

Estimating **4–6 sigma failure probabilities** in ngspice with the `highsigma`
command — the statistical analysis that matters for high-replication circuits
(SRAM bit cells, standard-cell libraries), where a per-cell failure of 1e-7 to
1e-9 must be quantified but plain Monte Carlo would need 1e7–1e9 runs to see any
failures at all.

## The method (scaled-sigma importance sampling)

`highsigma` inflates every Gaussian `.param`'s standard deviation by a factor
`lambda`, so the rare failure region is sampled *often*, then reweights each
sample by the likelihood ratio `p_nominal / p_inflated` to recover an **unbiased**
estimate of the true probability. It is **direction-free** — no gradient,
sensitivity analysis, or most-probable-failure-point search — so it is robust for
an arbitrary failure condition and needs only a few thousand runs.

## Usage

```
highsigma <N> [-scale <lambda>] [-seed <s>] [-analysis <cmd>]
          -metric <expr> [-max <hi>] [-min <lo>]
```

- **`N`** — number of importance samples (each re-sources the deck, redrawing the
  inflated `.param`s, and runs `-analysis`).
- **`-scale <lambda>`** — sigma-inflation factor (default 2; use ~2.5–3 for
  4–6 sigma).
- **`-analysis <cmd>`** — analysis to run per sample (default `op`; any ngspice
  analysis: `tran …`, `ac …`).
- **`-metric <expr>`** — the circuit quantity (a single ngspice expression token,
  e.g. `v(out)`, `-1/i(v1)`, `mag(v(out))`).
- **`-max <hi>` / `-min <lo>`** — the spec: a sample *fails* if the metric exceeds
  `hi` or falls below `lo` (give both for a two-sided spec; at least one is
  required). The comparison is done by the command rather than inside the
  expression because a bare `>`/`<` in a control command is an I/O redirect.

It reports the failure probability, its relative error, the equivalent one-sided
sigma-to-fail, and the raw failure count, and leaves them in the vectors/variables
`highsigma_pfail`, `highsigma_relerr`, `highsigma_sigma`, `highsigma_nfail`.

```
highsigma: 6000 samples, scale (sigma inflation) = 3, analysis 'op', fail if (-1/i(v1)) > 1150
  failures observed : 388 / 6000 (in the inflated sampling)
  P(fail)           : 3.2349e-06  +/- 3.26e-07  (relative error 10.1%)
  equivalent sigma  : 4.510  (one-sided, P = Phi(-sigma))
```

## Files

- **`highsigma_demo.cir`** — a Gaussian resistor with a 4.5-sigma spec limit; the
  estimate matches the analytic `Phi(-4.5) = 3.40e-6`. Run with
  `ngspice -b highsigma_demo.cir`.
- **`verify_highsigma.py`** — validation against the analytic `Phi(-beta)` ground
  truth (one Gaussian `.param` with failure `R > mu + beta*sigma` has probability
  `Phi(-beta)` exactly):
  1. accuracy at beta = 2 and 4 (moderate and rare) — P and equivalent sigma
     match `Phi(-beta)`;
  2. deep tail at beta = 5 (`Phi(-5) = 2.87e-7`) — estimated from a few thousand
     runs, where plain MC of the same N sees ~0 failures;
  3. two-sided spec (`-max` and `-min`) roughly doubles the tail probability;
  4. reproducibility — same seed gives the identical estimate;
  5. multi-parameter — two independent Gaussians combine as
     `N(., sqrt(s1^2 + s2^2))`.

```
python3 verify_highsigma.py
```

## Notes

- This is the second half of the statistical story that
  [Enhancement-149](../lhs_examples/) (Latin-Hypercube sampling) began: LHS lowers
  the variance of a *whole-distribution* estimate; `highsigma` reaches the *rare
  tail* that plain MC cannot.
- `highsigma` inflates **Gaussian** `.param`s (`agauss`/`gauss`); bounded uniform
  params (`aunif`/`unif`) are drawn at their nominal spread (weight 1), since a
  uniform has no tail to reach.
- It is a **front-end** feature (it changes only which parameter values are drawn,
  not the circuit solve), so it is solver-independent; being a heavy deck
  (thousands of re-sources) the verify runs under Sparse only.
- Every SPICE deck's first line is the **title** (ignored by the parser); the
  decks here start with a `*` title line accordingly.
