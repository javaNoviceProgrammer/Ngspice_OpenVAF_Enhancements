# Enhancement-74 — performance benchmark

A tracked performance baseline for the toolchain: how fast `openvaf-r`
compiles the flagship industry compact models, and how OSDI (compiled
Verilog-A) device evaluation compares against ngspice's hand-coded
built-in devices **on identical physics**.

## The twin methodology

Timing two *different* circuits tells you nothing. Every simulation
benchmark here is a **twin pair**: the same equations on both sides, once
as built-in devices (`r`, `c`, `d`, `nmos level=14`) and once as compiled
Verilog-A (`rcseg.va`, `vadiode.va`, VA-Models `bsim4.va`), with matching
model cards. ngspice then does the same numerical work — same Newton
iterations, same timestep trajectory — and the waveforms must agree, which
each run checks alongside the timing:

- **RC ladder** (linear): waveforms match to ~machine zero, same timepoint
  count — the ratio is pure per-evaluation OSDI overhead;
- **rectifier bank** (nonlinear diodes): `vadiode.va` mirrors the built-in
  diode's DC core + junction gmin + depletion/diffusion charge, agreement
  well below 1 mV;
- **BSIM4 stage**: the VA-Models BSIM4 (4.8) against ngspice's hand-coded
  C BSIM4 (`level=14 version=4.8`) on default cards — different codebases,
  so this one is a *correspondence* (op currents within a few %) plus a
  throughput comparison of a flagship compact model.

## Files

- `run_benchmark.py` — the full benchmark: [A] compile times over 12
  flagship corpus models (median of 3), [B] the twin throughput trio,
  [C] RC-ladder wall time vs circuit size. Writes `RESULTS.md`,
  `results.json`, `plots/*.png`.
- `bench_common.py` — toolchain resolution, deck generators, timing
  harness (shared with the verify script).
- `plot_benchmark.py` — renders the plots from `results.json`.
- `verify_benchmark.py` — the regression checks: everything deterministic
  (twin waveform matches, artifact presence) plus *generously* bounded
  sanity limits (OSDI/built-in < 25×, flagship compile < 60 s) so the
  suite never flakes on a slow machine yet still catches catastrophic
  regressions.
- `RESULTS.md`, `plots/` — the committed reference numbers (machine noted
  inside; regenerate locally for comparable figures).

The compile section uses the `VA_TEST/` corpus and skips gracefully when
it is absent (the physcheck-suite precedent).

## Round 2 (Enhancement-79)

Three sections extend the baseline:

- **[D] a 9-stage BSIM4 ring oscillator** — 18 compact-model devices,
  evaluation-dominated, with the oscillation frequencies doubling as a
  correspondence pin (built-in vs VA within ~1%);
- **[E] `.ac` and `.noise` throughput** on N=200 ladders — the `.noise`
  twin uses `nres.va`, a noisy resistor whose 4kT/R spectrum is
  *identical* to the built-in resistor's (the E-57 identity, re-pinned
  here to 7×10⁻⁷ while timing the adjoint solves);
- **[F] KLU vs SPARSE 1.3** — both device kinds, with `.options klu`
  (skipped gracefully on binaries built without KLU), plus a
  solver-independence pin: KLU and SPARSE waveforms agree to ~1e-15.

## Reference headline (see RESULTS.md for the full tables)

Compiled Verilog-A through OSDI runs within a small factor of ngspice's
hand-coded built-ins on identical physics — machine-zero-identical
waveforms — and `openvaf-r` compiles the entire flagship set of industry
compact models in well under a minute total.

## `large_bench.py` — the thousands-of-devices regime (2026-09-04)

`run_benchmark.py` measures small circuits. `large_bench.py` is its companion
for **40 000 BSIM4 MOSFETs and 67 000 OSDI instances**: four generated circuit
families (a BSIM4 / PSP 103 inverter chain, a resistor-diode mesh, a 2-D
BSIM4 grid, HiCUM L2 stages) at three or four sizes, each under **both**
solvers and against its built-in twin, with the op solution and two transient
probes diffed across every pair. Models are compiled from the VA-Models
corpus on demand; results accumulate in `large_results.json` (the committed
one is the reference run behind
[`docs/bug_hunts/2026-09-04_large-circuits-speed-and-correctness.md`](../../docs/bug_hunts/2026-09-04_large-circuits-speed-and-correctness.md)).

```bash
python3 large_bench.py --maxsize 300   # the small tier, a few minutes
python3 large_bench.py                 # everything; resumable in --budget chunks
python3 large_bench.py --report        # the tables
```

It is not part of the regression sweep (no `verify_` prefix): the full run
takes about ten minutes and one Sparse job is expected to time out.

