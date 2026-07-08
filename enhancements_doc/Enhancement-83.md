# Enhancement-83 — the transistor-level µA741: a complete model-to-circuit demo

This document describes Enhancement-83: the classic op-amp built entirely
from a Verilog-A BJT and characterized across DC, AC, and transient — a
complete "write a compact model, build a real circuit, measure
datasheet figures" workflow demonstration. No compiler or ngspice source
changes; the deliverable is the example (E-62 tutorial precedent).

## The model (`bjt741.va`)

A compact Gummel-Poon-flavored BJT in ~70 lines of Verilog-A: Ebers-Moll
transport with forward Early modulation, β-based ideal base currents,
standard depletion charges (via an analog function with the fc
linearization) plus diffusion charges on both junctions, `limexp` and the
simulator's gmin for convergence robustness. One module serves NPN and
PNP through polarity reflection (`type = ±1`, the corpus convention).
Pinned at a Gummel point: i_B = i_C,fwd/β to 4×10⁻⁷ relative, and the
PNP is the *exact* polarity mirror of the NPN.

## The circuit (`ua741.subckt`)

The textbook Fairchild topology, 20 transistors: Q1–Q4 input (npn
emitter followers into pnp common-base) with the Q5–Q7 active-load
mirror, Q8/Q9 common-mode bias mirror, Q10/Q11 Widlar source (R4 = 5 kΩ
→ the famous ~19 µA tail), Q12/Q13 master bias, the Q16/Q17 Miller
second stage with Cc = 30 pF, and the class-AB Q14/Q20 output behind a
2×V_BE stack. Protection devices omitted (behavioral demo, not
production silicon). The operating point converged first try with
textbook internal bias voltages.

## The measurements (11 checks, ALL PASS)

| Figure | This model | Real 741 (typ.) |
|---|---|---|
| Open-loop DC gain | **104.4 dB** | ~106 dB |
| Dominant pole | **5.6 Hz** | ~5 Hz |
| Unity-gain bandwidth | **0.754 MHz** | ~1 MHz |
| Phase margin (follower) | **87°** | 65–80° |
| Slew rate | **0.54 V/µs**, asymmetric like the original | 0.5 V/µs |
| Input offset | −0.39 mV | < 1 mV |
| Output swing (±15 V, 2 kΩ) | −13.1 … +14.0 V | ±13–14 V |

The centerpiece check is the **Miller single-pole identity**:
A_ol·f₋₃dB = 0.78 MHz vs the measured 0.75 MHz crossover (3%) — the
30 pF compensation doing its textbook job, verified across two
independent analyses. The figures *emerge from the topology*: the Widlar
tail and Cc produce the slew rate; nothing is programmed in. Even the
fine structure is authentic — the input-stage charge kick at the slew
edge and the Miller RHP-zero wiggle near 10 MHz appear because the
transistors are really there.

Two measurement crafts worth recording: the open-loop AC bias network
(feedback through 1 TH, injection through 1 MF) must have its corner far
below the amplifier's dominant pole or it masquerades as extra
low-frequency gain (an early 1 MH/1 F attempt inflated A_ol to 140 dB);
and phase margin in the inverting-injection configuration is cleanly
computed as 180° minus the phase *lag accumulated from the flat band*,
sidestepping wrap/convention pitfalls.

## Files (`opamp741_examples/`)

`bjt741.va`, `ua741.subckt`, `run_opamp741.py` (characterization →
`results/summary.txt`), `plot_opamp741.py` (the four-panel figure),
`verify_opamp741.py` (11 checks in generous windows — this is a
demonstrative model, not silicon), README with the reference table.

## Regression

No compiler or ngspice source changes; all 73 example verify suites pass
(this suite included), the integration suite 28/28.
