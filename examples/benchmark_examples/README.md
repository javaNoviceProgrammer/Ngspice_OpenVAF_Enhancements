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

## Reference headline (see RESULTS.md for the full tables)

Compiled Verilog-A through OSDI runs within a small factor of ngspice's
hand-coded built-ins on identical physics — machine-zero-identical
waveforms — and `openvaf-r` compiles the entire flagship set of industry
compact models in well under a minute total.
