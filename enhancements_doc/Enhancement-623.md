# Enhancement-623: `montecarlo -lhs` stratifies the model-declared draws too

**Scope:** `src/osdi/osdisetup.c` — under `-lhs` a draw's uniform is `(stratum + jitter) / N`,
the stratum this sample's rank among the N samples' hashes under the dimension's key
(`osdimc_lhs_stratum()`, `osdimc_lhs_u()`); `osdimc_z()` takes the inverse CDF of it (a
truncation confines the uniform instead of rejecting), the uniform shape takes it directly;
`OSDImcLhs()` turns it on for a command, `OSDImcSeedOffset(0)` and the interrupt reset turn it
off. `src/include/ngspice/osdiitf.h` declares it; `src/frontend/com_sweep.c` — `montecarlo -lhs`
calls it and the E-537 note that said the draws were not covered is gone.
`examples/lhs_examples/` grows 12 → 16 checks; `examples/mcpolicy_examples/` [26] checks the
strata instead of the note; handbook [§3.6](../docs/handbook/03-ngspice-workflows.md), the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §3, both suites'
READMEs. **ngspice only.** F5 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`lhs_examples`](../examples/lhs_examples/) 16 of 16, both solvers;
[`mcpolicy_examples`](../examples/mcpolicy_examples/) 46 of 46; `osdimc`, `osdidist`, `wcd`,
`huntfix`, `savemc`, `writemc`, `paramgiven`, `dcxsweep`, `constguard`, `autoopts`,
`mcfastpath`, `highsigma`, `montecarlo` green; full sweep 505 of 505.

## What was wrong

```spice
.option osdimc mcseed=1
.param rr = agauss(1000, 75, 3)
R1 a 0 {rr}
N1 a 0 rm
.model rm rstat r=1k
montecarlo 20 -lhs -seed 1 -analysis op -expr rn=@r1[resistance] -expr rm=@rm[r]
```
Sorted and mapped through Φ:
```
netlist  (LHS): 0.01 0.07 0.13 0.19 0.21 0.27 0.32 0.40 0.44 0.50 0.51 0.55 0.62 0.69 0.74 0.79 0.83 0.86 0.94 0.97
model-side    : 0.07 0.10 0.24 0.31 0.32 0.34 0.45 0.61 0.63 0.71 0.73 0.74 0.75 0.75 0.78 0.81 0.89 0.91 0.94 0.96
```

The netlist's Latin-Hypercube sampler lands each dimension's N samples one per stratum;
the osdimc draws were pure hashes of (seed, sample, owner, id) with no stratum to land in,
so beside the stratified `agauss` the `(* std *)` draws clumped — 0.71…0.78 six times of
twenty — under a banner that said "20 Latin-Hypercube samples". Enhancement-537 had the
command say so; the stratification the user asked for was still missing from the channel
that E-530's headline case ("the netlist carries no gauss()/agauss() at all") puts all its
variability in.

## What changed

Under `-lhs` a model-declared draw's uniform is **`(stratum + jitter) / N`**. The
stratum is this sample's rank among the N samples' hashes under the *dimension's* key —
(seed, owner, id), nothing of the sample — which is a random permutation of 0…N−1 as a pure
function: nothing stored, no RNG state, computed in O(N) per draw. The jitter is the draw's
own hash, as before. The Gaussian coordinate is the inverse CDF of that uniform; a
truncation confines the uniform to [Φ(−t), Φ(t)] instead of rejecting; a lognormal's log
coordinate is the same Gaussian; a uniform shape takes the uniform directly. Each dimension
has its own permutation, so two parameters' strata are independent (rank correlation 0.05
on the hunt's deck). Every design rule holds: the same seed reproduces the run bit for bit,
`-seed 2` is another valid Latin hypercube, a run without `-lhs` draws exactly what it
drew before (checked against the previous build: byte-identical), and `highsigma`, `wcd`
and the plain trials never see the flag — it is on between `montecarlo -lhs`'s start and
its end (`OSDImcSeedOffset(0)`), and the interrupt reset clears it.

```
netlist rn: strata [0, 1, 2, ..., 19]   one per stratum
model   rm: strata [0, 1, 2, ..., 19]   one per stratum
inst    dr: strata [0, 1, 2, ..., 19]   one per stratum
```

The note that `-lhs` did not cover these draws is gone; the banner's "Latin-Hypercube
samples" now covers both channels.

## Verification

| check | result |
|---|---|
| the hunt's deck, `montecarlo 20 -lhs -seed 1` | `rn` (netlist), `rm` (model) and `dr` (instance) each land one per stratum |
| uniform (half-width 50), lognormal (σ 0.2), tgauss (trunc 2) under `-lhs`, 16 and 20 samples | each one per stratum on its own uniform; the truncated one within ±2σ |
| `rm` vs `dr` rank correlation | 0.05 (hunt deck), 0.31 (the suite's five-parameter deck): independent permutations |
| the same deck without `-lhs` | byte-identical to the previous build; the model strata repeat |
| `-seed 1` twice; `-seed 2` | reproduces; a different, still valid hypercube |
| `mcpolicy` [26] (was: the note is printed) | the strata of `r` and `dr` over 16 samples |
| `lhs_examples` | 16 / 16, both solvers |
| full sweep | 505 of 505 |
