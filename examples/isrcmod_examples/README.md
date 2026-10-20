# isrcmod_examples — a current source's SFFM and AM read their delay and phases (Enhancement-912)

```
python3 verify_isrcmod.py
```

7 checks, both solvers (6 fail on E-911).

## The need

F3 of the 2026-10-19 correctness campaign. E-318 fixed the voltage source's SFFM and AM before
their delay; the current source kept the old code:
- **SFFM.** `SFFM(VO VA FC MDI FM TD PHASEM PHASEC)` read PHASEM from the TD slot and PHASEC from
  PHASEM's, dropped the last argument, and never applied TD. `SFFM(0 1 1meg 2 100k 5u 30 60)` was
  0.5 at the operating point where the voltage source gives 0.888651, and started at t = 0.
- **AM.** It returned 0 before its delay, and at t = 0 and the operating point even without one.

## What changed

The current source's SFFM and AM are the voltage source's: the arguments in their slots, the
waveform's start value held until TD, and `t − TD` after it.

## The checks

- **[1]–[4]** The SFFM current source:
  - 0.888651 at the operating point;
  - held to TD;
  - within 1e-9 of the manual's waveform at every point;
  - equal to the voltage source.
- **[5]** The delayed AM current source: 0.5 to TD, then the waveform, equal to the voltage
  source.
- **[6]** AM without a delay: 0.5 at the operating point and t = 0.
- **[7]** Control: SFFM without a delay or phases.
