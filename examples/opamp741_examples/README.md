# Enhancement-83 — the transistor-level µA741

The classic op-amp, built entirely from a Verilog-A BJT and simulated
across DC, AC, and transient — a complete "compact model to circuit"
workflow demo. The datasheet-class figures **emerge from the topology**
(the 30 pF Miller cap and the ~19 µA Widlar tail produce the 0.5 V/µs
slew and ~1 MHz GBW), rather than being programmed into a macromodel.

## Files

- `bjt741.va` — a compact Gummel-Poon-flavored BJT (~70 lines):
  Ebers-Moll transport with forward Early effect, β-based base currents,
  depletion charges via an analog function + diffusion charges, `limexp`
  and simulator gmin for convergence. One module serves NPN and PNP
  through `type = ±1`.
- `ua741.subckt` — the textbook Fairchild topology, 20 transistors:
  Q1–Q4 input with Q5–Q7 active load, Q8/Q9 mirror + Q10/Q11 Widlar
  bias, Q12/Q13, Q16/Q17 Miller stage (Cc = 30 pF), class-AB Q14/Q20
  output behind a 2×V_BE stack (protection devices omitted).
- `run_opamp741.py` — compiles the model and characterizes: DC follower
  sweep + open-loop transfer, open-loop AC via the classic L/C bias
  network, small-step and ±5 V-square transients. Writes `results/`.
- `plot_opamp741.py` — the four-panel figure (`plots/opamp741.png`).
- `verify_opamp741.py` — 11 checks in generous windows.

## Reference figures (vs. a real 741, typical)

| Figure | This model | Real 741 |
|---|---|---|
| Open-loop DC gain | 104 dB | ~106 dB |
| Dominant pole | 5.6 Hz | ~5 Hz |
| Unity-gain bandwidth | 0.75 MHz | ~1 MHz |
| Phase margin | 87° | 65–80° |
| Slew rate | 0.54 V/µs (asymmetric, like the original) | 0.5 V/µs |
| Input offset | −0.4 mV | < 1 mV |
| Swing (±15 V, 2 kΩ) | −13.1 … +14.0 V | ±13–14 V |

The Miller single-pole identity A_ol·f₋₃dB ≈ f_u holds to 3% — pinned as
a verify check. Even the fine structure is authentic: the input-stage
charge kick at the slew edge and the Miller RHP-zero wiggle near 10 MHz
appear because the transistors are really there.
