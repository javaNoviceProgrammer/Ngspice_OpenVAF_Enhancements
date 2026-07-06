# Enhancement-79 — benchmark round 2: ring oscillator, small-signal throughput, KLU vs SPARSE (version11)

This document describes Enhancement-79, extending Enhancement-74's
performance baseline with three sections — multi-device nonlinear
circuits, the small-signal analyses, and the solver comparison. Like
round 1, everything is a **twin** (same physics, built-in vs compiled
Verilog-A) with correctness pinned alongside every timing. No compiler or
ngspice source changes.

## [D] 9-stage BSIM4 ring oscillator

The missing regime in round 1: **evaluation-dominated, multi-device,
nonlinear**. 18 BSIM4 devices (9 CMOS inverters, `type=1`/`type=-1` VA
cards vs built-in `level=14` with matching W/L), kick-started with `uic`,
200 ns transient:

- both implementations oscillate, at **1.077 GHz (built-in) vs 1.065 GHz
  (OSDI)** — a 1.1% correspondence between two independent codebases of
  BSIM4 4.8, pinned as a verify check;
- wall-time ratio **1.91×** — the honest number this section exists for:
  with 18 compact-model evaluations per Newton iteration and a tiny
  matrix, per-instance call overhead compounds beyond the single-device
  1.26×. This is the workload where OSDI overhead is most visible.

## [E] `.ac` and `.noise` throughput

N=200 ladders: the RC twin from round 1 for `.ac` (300 pts/dec over nine
decades), and a new `nres.va` — a noisy resistor whose 4kT/R spectrum is
**identical** to the built-in resistor's (the E-57 identity) — for
`.noise`:

- `.ac` ratio **0.91×**, output identical to the last bit
  (max diff 0.0);
- `.noise` ratio **1.19×**, spectra matching to **7.6×10⁻¹⁵** over 601
  points — the adjoint solves do the same work on both sides;
- both runs are sub-0.1 s: the small-signal analyses are factorization-
  dominated, so OSDI evaluation overhead barely registers.

## [F] KLU vs SPARSE 1.3

`.options klu` after the title line (the E-1 recipe), both device kinds,
on the N=500 ladder and the ring oscillator — and an honest wash:
**speedups 0.91–1.00×**. These matrices (a tridiagonal ladder, an
18-device ring) are too small and too regular for KLU's AMD/BTF ordering
to pay for itself; the Enhancement-1 mesh benchmark remains the reference
for where KLU wins (large, denser matrices). The valuable pin that stays:
**KLU and SPARSE waveforms agree to ~10⁻¹⁵** — solver independence as a
regression check, run whenever the binary has KLU and skipped gracefully
otherwise (the section auto-detects; local and CI binaries both carry
KLU).

## Examples (`benchmark_examples/`, grows to 12 checks, ALL PASS)

`run_benchmark.py` gains sections [D]/[E]/[F] (`ro_deck`,
`ac_ladder_deck`, `noise_ladder_deck`, `with_klu`, `osc_freq` in
`bench_common.py`; `nres.va` new); `RESULTS.md`, `results.json` and the
plots regenerated (new `klu_vs_sparse.png`; the throughput bars now carry
all six benches). The three new verify checks: ring oscillators oscillate
with corresponding frequencies (< 10%), the noise-spectrum identity
(< 10⁻⁴), and KLU ≡ SPARSE waveforms (< 10⁻⁶).

## Regression

No compiler or ngspice source changes; all 70 example verify suites pass
(this suite's 12 included), the integration suite 28/28.
