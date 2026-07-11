# Enhancement-149 — Latin-Hypercube Monte Carlo sampling (`mcsample`)

ngspice's Monte Carlo works by drawing each random parameter independently from the
PRNG — `.param rr = agauss(1k, 100, 3)` re-thrown on every `reset`. That is plain
random sampling: with a modest run count the draws clump in some regions of the
distribution and leave gaps in others, and the estimated mean / spread / yield
converges only as `1/√N`. Commercial simulators offer **low-discrepancy sampling**
(Latin-Hypercube, Sobol) to fix this; ngspice had none — it was a ❌ row in the
[gap analysis](../docs/internals/ngspice_internals/ngspice_gaps.md).

Enhancement-149 adds **Latin-Hypercube sampling (LHS)** through a new `mcsample`
command. LHS partitions every random dimension's probability range into `N` equal
strata and draws **exactly one sample per stratum** (with an independent stratum
permutation per dimension), so `N` runs cover each distribution evenly instead of
clumping. For smooth responses this cuts the variance of the estimate by one to two
orders of magnitude at the same `N` — measured **~130× lower** here.

## Usage

```
mcsample lhs <N> [seed <s>]   engage LHS for the next N reset-driven runs
mcsample random | off         revert to independent PRNG draws
mcsample                      report the current sampling mode
```

Once `mcsample lhs N` is set, the **existing** netlist Monte Carlo idiom is
unchanged — the stochastic `.param` functions **`agauss` / `gauss` / `aunif` /
`unif` / `limit`** simply draw stratified values instead of independent ones, one
sample per `reset`:

```spice
.param rr = agauss(1000, 100, 3)     ; ~ N(1000, 33.33)
V1 a 0 DC 1
R1 a 0 {rr}
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

Each stochastic function call within one `reset` pass is one LHS **dimension**, so a
deck with several random parameters stratifies each of them independently. Gaussian
draws (`agauss`/`gauss`) are stratified in probability space and mapped through the
inverse-normal CDF, so the tails are covered evenly too.

## Implementation notes

- **Sampler** (`maths/misc/randnumb.c`, declared in `randnumb.h`): holds the mode,
  `N`, current sample index, per-sample dimension counter and seed. Each dimension's
  stratum **permutation** (Fisher–Yates over `0..N-1`) and per-sample **jitter** are
  generated lazily on first use from a self-contained `splitmix64` seeded by
  `(seed, dimension)`, so the whole sequence is reproducible and independent of
  evaluation order. `mc_sample_uniform()` returns `(perm[d][i] + jitter[d][i]) / N`;
  `mc_sample_gauss()` maps that uniform through **`inv_normal_cdf`** (Acklam's
  probit, rel. error < 1.15e-9).
- **Sample boundary**: one full deck re-evaluation pass == one Monte Carlo sample.
  `numparam/spicenum.c`'s `nupa_signal(NUPADECKCOPY)` edge (once per `reset`
  re-source, guarded by the existing `firstsignalS` latch) calls
  `mc_sample_advance()`, which steps the sample index and rewinds the dimension
  counter before that pass's `.param` draws run.
- **Draw hook** (`numparam/xpressn.c`): `agauss`/`gauss` take one `mc_sample_gauss()`
  and `aunif`/`unif`/`limit` take one `2·mc_sample_uniform()-1` when LHS is active,
  falling back to the plain `gauss1()`/`drand()` otherwise — so behaviour with LHS
  off is byte-identical to before.
- **Command** `com_mcsample` (`randnumb.c`, registered in `commands.c`): parses
  `lhs <N> [seed <s>]` / `random` / `off`.
- LHS is a **front-end** feature — it changes only which uniform/Gaussian values the
  stochastic `.param` functions draw, not the circuit solve — so results are
  identical under the Sparse 1.3 and KLU solvers.

## Verification

`examples/lhs_examples/verify_lhs.py` (5 groups, all passing under **both** solvers):

- **[1] stratification** — `N=48` LHS draws of a Gaussian `.param` occupy each of the
  48 probability strata **exactly once** (the defining Latin-hypercube property);
  plain random sampling leaves gaps (≈32/48 distinct strata).
- **[2] multi-dimension** — two independent params (`agauss` + `aunif`) are **both**
  fully stratified in the same run.
- **[3] variance reduction** — over 40 independent trials, `Var(sample-mean)` under
  LHS is **~130× smaller** than under plain random MC at the same `N=32`, both
  converging to the same mean.
- **[4] reproducibility** — the same seed reproduces the sample set bit-for-bit; a
  different seed gives a different set.
- **[5] correctness** — LHS sample mean/stddev match the analytic distribution
  (`agauss(nom, avar, sig)` has σ = avar/sig; `aunif(nom, avar)` is uniform on
  `[nom−avar, nom+avar]`).

`lhs_demo.cir` is a runnable resistor-divider demo (`N=64` random vs LHS).

## Scope and follow-ups

Latin-Hypercube low-discrepancy sampling for the `reset`-driven `.param` Monte Carlo
idiom, engaged with one command and reproducible by seed. Follow-ups: a **Sobol**
sequence option (needs direction-number tables but does not require `N` up front),
extending stratification to the nutmeg-loop `sgauss(0)`/`sunif(0)` idiom, and — the
natural next statistical brick — **high-sigma** methods (importance sampling /
worst-case distance) that build on top of a good sampler.
