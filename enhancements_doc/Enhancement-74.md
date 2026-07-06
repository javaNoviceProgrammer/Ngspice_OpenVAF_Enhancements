# Enhancement-74 — performance benchmark: OSDI vs built-in twins + flagship compile times (version11)

This document describes Enhancement-74: a **tracked performance baseline**
for the toolchain — the first quantitative answer to "how fast is compiled
Verilog-A?" in this project. Like Enhancements 57/60/66/69, the deliverable
is a permanent, rerunnable measurement suite; no compiler or ngspice source
changes.

## The twin methodology

Timing two different circuits proves nothing, so every simulation benchmark
is a **twin pair**: the same equations once as ngspice built-in devices and
once as compiled Verilog-A, with matching model cards — ngspice then does
the same numerical work (same Newton iterations, same timestep trajectory)
and the waveforms must agree, which every run checks alongside the timing:

- **RC ladder** (`rcseg.va` vs built-in `r`+`c`, 200 segments, 100 306
  timepoints): waveforms match to **8.9×10⁻³² V** — the integrator followed
  the *identical* trajectory (same point count), so the ratio is pure
  per-evaluation OSDI overhead;
- **rectifier bank** (`vadiode.va` mirroring the built-in diode's DC core +
  junction gmin + depletion/diffusion charge, 50 cells): agreement
  2.8×10⁻⁵ V through a strongly nonlinear transient;
- **BSIM4 stage** (VA-Models `bsim4.va` 4.8 vs the hand-coded C
  `level=14 version=4.8`, default cards): different codebases — a
  *correspondence* pin (op drain currents within 3.9%) plus a flagship
  compact-model throughput comparison.

## Reference numbers (Apple Silicon; RESULTS.md has the full tables)

- **Twin throughput**: RC ladder ratio **0.99** — compiled Verilog-A
  through OSDI matches hand-coded C outright on identical physics;
  rectifier **1.26×**; BSIM4 stage **1.26×** (~185 000 timepoints/s).
- **Scaling** (RC ladder N = 10…500): the OSDI/built-in ratio stays
  1.00–1.07 across a 50× size range — the overhead does not grow with
  circuit size.
- **Compile time** (median of 3): all 12 flagship industry models —
  BSIM4/6/BULK/CMG/SOI, PSP 102/103, HiCUM L2, MEXTRAM 505, EKV3,
  ASM-HEMT, diode_cmc — compile in **0.4–3.8 s each, ~21 s total**
  (lines counted through their `include` bodies).

## A benchmarking trap worth recording

The first N=500 OSDI ladder run died on ngspice's protective plot-memory
guard ("memory required is more than memory available"): batch-mode `tran`
stores **every node vector** by default, and ~500 vectors × 25k points
tripped the estimate against momentary free RAM. The fix is benchmarking
hygiene that also purifies the measurement: `save v(<probe>)` before the
`tran` — output storage drops from N vectors to one, and the RC-ladder
ratio improved from 1.08 to 0.99 (the "overhead" had been partly plot
storage, not device evaluation). The guard's message printing literal
"(Id Bytes)" (a `%Id` format specifier that macOS printf doesn't know) is
noted as a stock-ngspice cosmetic quirk.

## A second trap: provenance in the committed artifacts

The verify script originally passed absolute `HERE`-joined paths to
`openvaf-r`, which embeds the source path (LLVM `comp_dir`) into the
`.osdi` — silently re-polluting the committed artifacts every verify run.
Worse, the standing fold check missed it: **macOS `strings` without `-a`
skips the section carrying the path** (a raw `grep -a` on the binary
catches it). Fixed by having `compile_va` relativize every path against
the example dir; the fold check is upgraded to raw-byte grep.

## Examples (`benchmark_examples/`, 8 checks, ALL PASS)

`run_benchmark.py` (the full benchmark: compile times, twin trio, scaling
sweep → `RESULTS.md`, `results.json`, `plots/*.png`), `bench_common.py`
(deck generators + timing harness), `plot_benchmark.py`,
`verify_benchmark.py`. The verify checks pin only what is deterministic or
generously bounded, so the suite never flakes on a slow machine: the twin
waveform matches (< 10⁻⁹ / < 10⁻³ / < 10%), the artifacts' presence, and
catastrophic-regression limits (OSDI/built-in < 25×, flagship compile
< 60 s). The compile section skips gracefully without the `VA_TEST/`
corpus (the physcheck precedent).

## Regression

No compiler or ngspice source changes; all 67 example verify suites pass
(this suite included), the integration suite 28/28, and the VA_TEST corpus
compiles 92/92.
