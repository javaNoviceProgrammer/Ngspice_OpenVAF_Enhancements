# sffmdefault_examples — SFFM's default frequencies are the manual's (Enhancement-913)

```
python3 verify_sffmdefault.py
```

6 checks, both solvers (4 fail on E-911).

## The need

F4 of the 2026-10-19 correctness campaign. The manual's table gives SFFM's carrier FC a default of
500/TSTOP and its modulation FM 5/TSTOP; both sources had them swapped. `SFFM(0 1)` over 1 ms was
a 5 kHz carrier modulated at 500 kHz, and MDI was clamped to FC/FM = 0.01 with a warning.

The manual orders the arguments two ways:
- its table and the sources section's example read VO VA FC MDI FM, as the code and SPICE3 do;
- its general-form line and its SFFM example read FM MDI FC.

## What changed

FC defaults to 500/TSTOP and FM to 5/TSTOP. The argument order stays. When MDI is clamped because
the carrier is below its modulation, the warning says so and names the order SFFM reads.

## The checks

- **[1]** `SFFM(0 1)`: carrier 500 kHz, modulation 5 kHz, MDI 90 at every point, no warning.
- **[2]** `SFFM(0 1 1meg)`: the modulation defaults to 5 kHz, MDI unclamped.
- **[3]** The manual's SFFM example: the warning names the carrier below the modulation.
- **[4]** The sources section's example `SFFM(0 1 10K 5 1K)`: no warning, the waveform.
- **[5]** Control: a fully written SFFM, unchanged.
