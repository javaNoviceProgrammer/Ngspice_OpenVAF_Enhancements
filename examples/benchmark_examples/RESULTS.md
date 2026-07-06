# Enhancement-74 benchmark results (reference run)

- Machine: Apple M2 Ultra — Darwin 25.5.0, arm64
- Toolchain: this repository's openvaf-r + ngspice-46 (see the git tag)
- Date: 2026-07-06

Timing is machine-dependent; regenerate with `python3 run_benchmark.py` for numbers comparable on your machine.

## [A] Compile time (openvaf-r, median of 3)

| Model | Lines (incl. includes) | Compile |
|---|---:|---:|
| BSIM4 (4.8) | 9723 | 2.29 s |
| BSIM6 (6.1.1) | 4548 | 1.62 s |
| BSIM-BULK | 5228 | 2.50 s |
| BSIM-CMG | 6871 | 3.90 s |
| BSIM-SOI | 8172 | 1.66 s |
| PSP 103 | 6642 | 2.23 s |
| PSP 102 | 5980 | 1.60 s |
| HiCUM L2 (3.0) | 1581 | 0.46 s |
| MEXTRAM 505 | 2445 | 0.37 s |
| EKV 3 | 4749 | 0.43 s |
| ASM-HEMT | 2100 | 3.54 s |
| diode_cmc | 2653 | 0.81 s |

Total for the 12 flagships: **21.4 s**.

## [B] Simulation throughput: OSDI vs built-in twins

Identical physics on both sides (same equations, same model card),
so ngspice does the same numerical work and the waveforms agree;
the ratio isolates the OSDI evaluation overhead.

| Benchmark | built-in | OSDI | OSDI/built-in | timepoints | OSDI pts/s | max waveform diff |
|---|---:|---:|---:|---:|---:|---:|
| rcladder | 2.44 s | 2.37 s | 0.97 | 100306 | 42418 | 8.89e-32 V |
| rectifier | 0.28 s | 0.37 s | 1.32 | 20008 | 53745 | 2.77e-05 V |
| bsim4stage | 0.21 s | 0.27 s | 1.26 | 50008 | 186199 | 6.87e-03 V |

## [C] RC-ladder scaling (wall time vs circuit size)

| N segments | built-in | OSDI | ratio |
|---:|---:|---:|---:|
| 10 | 0.11 s | 0.11 s | 1.03 |
| 20 | 0.14 s | 0.14 s | 1.00 |
| 50 | 0.20 s | 0.20 s | 1.00 |
| 100 | 0.33 s | 0.33 s | 0.99 |
| 200 | 0.58 s | 0.59 s | 1.00 |
| 500 | 1.31 s | 1.40 s | 1.07 |

## [D] 9-stage BSIM4 ring oscillator

18 BSIM4 devices, evaluation-dominated; the oscillation
frequencies double as a correspondence pin.

| | built-in | OSDI | OSDI/built-in |
|---|---:|---:|---:|
| wall time | 1.03 s | 1.97 s | 1.91 |
| frequency | 1.077 GHz | 1.065 GHz | — |

## [E] Small-signal throughput (ladders, N = 200)

| Analysis | built-in | OSDI | OSDI/built-in | max output diff |
|---|---:|---:|---:|---:|
| .ac | 0.05 s | 0.05 s | 0.91 | 0.00e+00 |
| .noise | 0.04 s | 0.04 s | 1.19 | 7.60e-15 |

## [F] KLU vs SPARSE 1.3

| Benchmark | devices | SPARSE | KLU | KLU speedup |
|---|---|---:|---:|---:|
| rcladder500 | bi | 1.30 s | 1.43 s | 0.91x |
| rcladder500 | osdi | 1.40 s | 1.53 s | 0.92x |
| ringosc | bi | 1.04 s | 1.04 s | 1.00x |
| ringosc | osdi | 1.96 s | 2.01 s | 0.98x |


![scaling](plots/scaling.png)

![throughput](plots/throughput.png)

![compile](plots/compile_times.png)
