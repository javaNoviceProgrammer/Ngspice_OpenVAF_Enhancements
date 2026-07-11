# Enhancement-150 — high-sigma rare-event estimation (`highsigma`)

[Enhancement-149](Enhancement-149.md) made ordinary Monte Carlo *efficient*
(Latin-Hypercube stratification of the whole distribution). This enhancement
reaches the part of the distribution ordinary Monte Carlo **cannot** reach at all:
the **rare tail**. For high-replication circuits — an SRAM bit cell instantiated
millions of times, a standard-cell library used everywhere — the quantity that
matters is a per-cell failure probability of `1e-7` to `1e-9`, i.e. a 4–6 sigma
event. Plain Monte Carlo would need `1e7`–`1e9` runs just to *see* a handful of
failures, which is infeasible. This was the last ❌ statistical row versus a
commercial simulator in the [gap analysis](../docs/internals/ngspice_internals/ngspice_gaps.md).

Enhancement-150 adds a **`highsigma`** command that estimates such probabilities
with a few thousand runs, using **scaled-sigma importance sampling**.

## The method

Every Gaussian `.param`'s standard deviation is inflated by a factor `lambda`
(the "scaled sigma"), so the rare failure region is sampled *often*; each sample
is then reweighted by the likelihood ratio `p_nominal(x) / p_inflated(x)` so the
estimator `P̂ = (1/N) Σ wᵢ·1[failᵢ]` is **unbiased** for the true (nominal)
probability. Scaled-sigma sampling is **direction-free** — unlike mean-shift
importance sampling or worst-case-distance search it needs no gradient,
sensitivity, or most-probable-failure-point, so it is robust for an arbitrary
failure condition. The per-dimension log-weight
`log λ − (z²/2)(1 − 1/λ²)` is accumulated over a sample's Gaussian draws.

## Usage

```
highsigma <N> [-scale <lambda>] [-seed <s>] [-analysis <cmd>]
          -metric <expr> [-max <hi>] [-min <lo>]
```

- **`N`** importance samples; each re-sources the deck (redrawing the inflated
  `.param`s) and runs `-analysis` (default `op`).
- **`-scale <lambda>`** sigma inflation (default 2; ~2.5–3 for 4–6 sigma).
- **`-metric <expr>`** the circuit quantity — one ngspice expression token
  (`v(out)`, `-1/i(v1)`, `mag(v(out))`).
- **`-max <hi>` / `-min <lo>`** the spec: a sample fails if the metric is above
  `hi` or below `lo` (give both for a two-sided spec; at least one is required).
  The comparison is done by the command, not inside the expression, because a bare
  `>`/`<` in a control-language command is an I/O redirect.

It reports the failure probability, its relative error, the equivalent one-sided
sigma-to-fail (`−Φ⁻¹(P̂)`), and the raw failure count, and leaves them in the
vectors/variables `highsigma_pfail`, `highsigma_relerr`, `highsigma_sigma`,
`highsigma_nfail` for scripting.

```
* fail if R > mean + 4.5 sigma; analytic P = Phi(-4.5) = 3.40e-6
highsigma 6000 -scale 3.0 -seed 1 -analysis op -metric -1/i(v1) -max 1150
  ->  P(fail) = 3.23e-06  (equivalent sigma 4.510)   [388 failures in the inflated 6000]
```

## Implementation notes

- **Sampler** (`maths/misc/randnumb.c`): a new `MC_MODE_SSS` reuses the E-149
  sampler scaffolding. `mc_sample_gauss()` draws `z = λ·gauss1()` from the inflated
  normal and accumulates that draw's log likelihood-ratio into `sss_logw`;
  `mc_sample_weight() = exp(sss_logw)`. Uniform `.param`s are bounded, so SSS does
  not inflate them (weight 1). `mc_sss_config(N, λ, seed)` engages it (and seeds
  the global PRNG for reproducibility); `mc_sss_off()` reverts.
- **Command** `com_highsigma` lives in `frontend/com_sweep.c` — it reuses that
  file's synchronous command runner (`sw_run_cmd`, for `reset` + the inner
  analysis) and expression evaluator (`sw_eval_expr`), and is likewise a
  sampling-driven analysis loop. Registered in `commands.c`.
- The loop is the ordinary reset-driven MC idiom driven from C: for each sample it
  runs `reset` (redraws the inflated params on the `NUPADECKCOPY` edge from E-149),
  runs `-analysis`, evaluates `-metric`, applies the spec, and reads
  `mc_sample_weight()`. `ft_optimizing` silences per-sample chatter.
- Front-end only, so solver-independent.

## Verification

`examples/highsigma_examples/verify_highsigma.py` (Sparse-only — a heavy,
thousands-of-re-sources deck; solver-independent). Ground truth: one Gaussian
`.param` with failure `R > mu + beta·sigma` has probability `Phi(-beta)` exactly.

- **[1]** accuracy at `beta = 2` and `4` — P **and** equivalent sigma match
  `Phi(-beta)` (e.g. beta 4: sigma-to-fail 4.000, P 3.16e-5 vs 3.17e-5).
- **[2]** deep tail `beta = 5` (`Phi(-5) = 2.87e-7`) — estimated from 6000 runs
  (sigma 5.01), where plain MC of the same N expects ~0.0017 failures.
- **[3]** a two-sided spec (`-max` and `-min`) roughly doubles the tail
  probability and lowers the equivalent sigma accordingly.
- **[4]** reproducibility — same seed gives the identical estimate bit-for-bit.
- **[5]** multi-parameter — two independent Gaussians combine as
  `N(·, sqrt(s1²+s2²))`; the recovered sigma-to-fail matches.

`highsigma_demo.cir` is a runnable 4.5-sigma demo.

## Scope and follow-ups

Direction-free rare-event probability estimation, reaching 4–6 sigma with a few
thousand runs and reporting an unbiased P(fail) with a confidence (relative error)
and an equivalent sigma-to-fail. Follow-ups: **worst-case-distance / mean-shift**
importance sampling (more efficient once the failure direction is known — the
most-probable-failure-point can seed the shift), **adaptive lambda** selection, and
combining SSS with the E-149 stratification (stratified importance sampling).
