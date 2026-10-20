# Enhancement-912: a current source's SFFM applies its delay and reads its two phases, and its AM keeps its offset before the delay — `SFFM(0 1 1meg 2 100k 5u 30 60)` took the delay as a modulation phase and the modulation phase as the carrier's, and an AM current source was 0 at the operating point

**Scope:** F3 of the
[sources, code models, operators and statistics correctness campaign of 2026-10-19](../docs/bug_hunts/2026-10-19_ngspice-openvaf-r-sources-models-statistics-correctness-campaign.md).
The voltage source had both fixed by [E-318](Enhancement-318.md).

ngspice:
- `spicelib/devices/isrc/isrcload.c`:
  - SFFM reads TD, PHASEM and PHASEC from their own slots and holds its start value until TD.
  - AM holds its start value until TD.
- `spicelib/devices/vsrc/vsrcload.c`: a comment that said the current source already held.

**ngspice only.**

**Suites:**
- [`isrcmod_examples`](../examples/isrcmod_examples/) (new): 7 checks per solver, 6 of which fail
  on E-911.
- `sffmoffset` (E-318), `srcnote`, `isrcpulse`, `argdiscard` and `pulsedefault`, unchanged.
- The full sweep: 600 of 600.

## What was wrong

```
V1 a 0 SFFM(0 1 1meg 2 100k 5u 30 60)
I1 0 b SFFM(0 1 1meg 2 100k 5u 30 60)
V2 c 0 AM(0.5 1 0.5 100k 1meg 5u)
I2 0 d AM(0.5 1 0.5 100k 1meg 5u)
```

SFFM's arguments are VO VA FC MDI FM TD PHASEM PHASEC. Into 1 Ω:

| | `op` | at 2 µs | at 7.3 µs | the waveform |
|---|---|---|---|---|
| V1 SFFM | 0.888651 | 0.888651 | −0.997647 | 0.888651 held to 5 µs |
| **I1 SFFM** | **0.500000** | **0.655990** | **0.411560** | |
| V2 AM | 0.5 | 0.5 | 1.92226 | 0.5 held to 5 µs |
| **I2 AM** | **0** | **0** | 1.92226 | |

`isrcload.c` read:
- `TD` from the TD slot, and then `PHASEM` from it too: the 5 µs became a modulation phase of
  5e-6 degrees;
- `PHASEC` from PHASEM's slot: the 30° became the carrier phase, and the 60° was never read;
- and it never subtracted `TD` from the time, so the waveform started at t = 0.

Its AM returned 0 for `time <= TD`. That is also true at t = 0 and at the operating point when
there is no delay, so `AM(0.5 1 0.5 100k 1meg)` as a current source was 0 there where the
waveform is 0.5. E-318 had fixed exactly this in `vsrcload.c`. Its suite's note that the current
source "has no such zeroing" was true of SFFM only because SFFM never applied the delay at all.

In the campaign's 1,500 random sources, 45 current-source SFFM cases and 66 AM cases differed
from the manual this way.

## What changed

The current source's SFFM and AM are the voltage source's, line for line:
- SFFM reads PHASEM from the seventh argument and PHASEC from the eighth.
- Both hold the waveform's value at its start until TD, and run on `t − TD` after it:
  - SFFM's start value is VO + VA·sin(PHASEC + MDI·sin PHASEM);
  - AM's is VO + (VMO + VMA·sin PHASEM)·sin PHASEC.

The deck above now reads the same for I1 as for V1, and for I2 as for V2, at every point.

## The checks

`isrcmod_examples` (new), under both solvers, each source as V and as I into 1 Ω:
- **[1]** The SFFM current source is 0.888651 at the operating point (E-911: 0.5).
- **[2]** ... held there up to TD = 5 µs.
- **[3]** ... within 1e-9 of the manual's waveform at every accepted point (measured 6e-14).
- **[4]** ... equal to the voltage source at every one of its 2008 points.
- **[5]** The delayed AM current source: 0.5 at the operating point and up to TD (E-911: 0), the
  waveform after it, equal to the voltage source.
- **[6]** AM without a delay: 0.5 at the operating point and t = 0 (E-911: 0).
- **[7]** Control: SFFM without a delay or phases, unchanged.

## Limits

- **Breakpoints.** Neither source places one at TD, so the step that crosses the delay is not
  cut there. That is as for the voltage source.
- **The operating-point Note.** "dc value used for op instead of transient time=0 value" judges
  an SFFM or AM line by its first or second argument, not by the waveform's start value. That is
  as for the voltage source.
- **SFFM's defaults.** These are F4 of the campaign: FC = 5/TSTOP and FM = 500/TSTOP are swapped
  against the manual's table, in both sources.
