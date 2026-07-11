# lhs_examples — Latin-Hypercube Monte Carlo sampling (Enhancement-149)

Low-discrepancy **Latin-Hypercube sampling (LHS)** for ngspice Monte Carlo,
exposed through a new `mcsample` command. LHS is the industry-standard variance
reduction for SPICE statistical runs: for the same number of samples it estimates
the mean / spread / yield far more accurately than plain random Monte Carlo.

## Why

Plain Monte Carlo draws every random parameter independently from the PRNG, so a
modest run count clumps in some regions and leaves gaps in others, and the
estimate converges only as `1/sqrt(N)`. Latin-Hypercube sampling instead splits
each random dimension's probability range into `N` equal strata and draws
**exactly one sample per stratum** (with an independent stratum permutation per
dimension). The clumping disappears and, for smooth responses, the variance of
the estimate drops by one to two orders of magnitude at the same `N`.

## Usage

```
mcsample lhs <N> [seed <s>]   engage LHS for the next N reset-driven runs
mcsample random | off         revert to independent PRNG draws
mcsample                      report the current sampling mode
```

Once `mcsample lhs N` is set, the existing netlist Monte Carlo idiom is unchanged
— the stochastic `.param` functions **`agauss` / `gauss` / `aunif` / `unif` /
`limit`** simply draw stratified values instead of independent ones, one sample
per `reset`:

```
.param rr = agauss(1000, 100, 3)     ; ~ N(1000, 33.33)
...
.control
  mcsample lhs 64 seed 1
  let run = 0
  dowhile run < 64
    reset          ; steps to the next stratified sample
    op
    let iv[run] = i(V1)
    let run = run + 1
  end
  print mean(iv) stddev(iv)
.endc
```

Each stochastic function call within one `reset` pass is one LHS *dimension*, so
a deck with several random parameters stratifies each of them independently.
Gaussian draws (`agauss`/`gauss`) are stratified in probability space and mapped
through the inverse-normal CDF, so the tails are covered evenly too.

## Files

- **`lhs_demo.cir`** — a resistor divider with two random resistors; runs `N=64`
  plain-random and LHS Monte Carlo and prints the sample mean/stddev of each.
  Run with `ngspice -b lhs_demo.cir`.
- **`verify_lhs.py`** — the validation harness (runs under both the Sparse and KLU
  solvers, since LHS is a front-end feature and must be solver-independent):
  1. **stratification** — `N` LHS samples of a Gaussian `.param` occupy each of
     the `N` probability strata exactly once; plain random leaves gaps.
  2. **multi-dimension** — two independent params (`agauss` + `aunif`) are both
     fully stratified in the same run.
  3. **variance reduction** — over many trials, `Var(sample-mean)` under LHS is
     ~100× smaller than under plain random MC at the same `N`.
  4. **reproducibility** — same seed reproduces bit-for-bit; a different seed
     gives a different sample set.
  5. **correctness** — LHS sample mean/stddev match the analytic distribution
     (`agauss(nom, avar, sig)` has σ = avar/sig; `aunif(nom, avar)` is uniform on
     `[nom−avar, nom+avar]`).

```
python3 verify_lhs.py
```

## Notes

- LHS is a **front-end** feature — it changes only which uniform/Gaussian values
  the stochastic `.param` functions draw, not the circuit solve — so results are
  identical under the Sparse 1.3 and KLU solvers.
- The nutmeg-loop Monte Carlo idiom (`sgauss(0)`/`sunif(0)` + `alter`, no `reset`)
  is not affected by `mcsample`; LHS targets the `reset`-driven `.param` idiom,
  which has a well-defined per-sample boundary.
- Every SPICE deck's first line is the **title** (ignored by the parser); the
  decks here start with a `*` title line accordingly.
