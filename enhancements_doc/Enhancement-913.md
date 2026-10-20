# Enhancement-913: SFFM's default frequencies are the manual's, carrier above modulation — `SFFM(0 1)` was a 5 kHz carrier modulated at 500 kHz with its modulation index clamped to 0.01, and the manual's own example, written in its general form's order, now says why it clamps

**Scope:** F4 of the
[sources, code models, operators and statistics correctness campaign of 2026-10-19](../docs/bug_hunts/2026-10-19_ngspice-openvaf-r-sources-models-statistics-correctness-campaign.md).

ngspice:
- `spicelib/devices/vsrc/vsrcload.c`, `spicelib/devices/isrc/isrcload.c`, in SFFM:
  - FC defaults to 500/TSTOP and FM to 5/TSTOP;
  - when MDI is clamped because the carrier is below its modulation, the warning says so and names
    the argument order.

**ngspice only.**

**Suites:**
- [`sffmdefault_examples`](../examples/sffmdefault_examples/) (new): 6 checks per solver, 4 of which
  fail on E-911.
- `sffmoffset`, `isrcmod`, `srcnote`, `isrcpulse`, `argdiscard`, `pulsedefault` and `guardspell`,
  unchanged.
- The full sweep: 601 of 601.

## What was wrong

The manual's SFFM table:

| | | default |
|---|---|---|
| FC | carrier frequency | 500/TSTOP |
| MDI | modulation index | 90 |
| FM | modulating frequency | 5/TSTOP |

The default MDI is 0.9·FC/FM, as the code's comment beside it says. The code had the two
frequencies swapped:
- FC defaulted to 5/TSTOP and FM to 500/TSTOP, a modulation a hundred times faster than its
  carrier.
- `V1 a 0 SFFM(0 1)` with `tran 1u 1m` was therefore a 5 kHz carrier modulated at 500 kHz. It
  crossed zero rising at 0.2, 0.4 and 0.6 ms, and printed `Warning: MDI in v1 limited to FC/FM`:
  MDI was clamped to FC/FM = 0.01.
- `SFFM(0 1 1meg)` took 500 kHz for its modulation and had its MDI clamped to 2.

The manual gives the arguments in two orders:
- **VO VA FC MDI FM.** This is the order of its table, of the sources section's example
  `ISRC 23 21 AC 0.333 45.0 SFFM(0 1 10K 5 1K)`, and of the code and SPICE3.
- **VO VA FM MDI FC.** This is its general-form line. Its SFFM example
  `V1 12 0 SFFM(0 2 20 45 1k 1m 0 0)` is written in that order: read in the code's order, it is a
  20 Hz carrier modulated at 1 kHz, and its MDI of 45 is clamped to 0.02.

## What changed

- **The defaults.** FC defaults to 500/TSTOP and FM to 5/TSTOP, in both sources, as the table has
  them. `SFFM(0 1)` over 1 ms is a 500 kHz carrier modulated at 5 kHz with an MDI of 90. Its
  waveform matches the manual's equation at every point, and no warning is printed.
- **The order.** The argument order is unchanged. It is the code's, SPICE3's and the table's;
  following the general-form line would change the meaning of every deck that writes SFFM in full.
- **The warning.** When MDI is clamped because the carrier is below its modulation, the warning
  now says why:

```
Warning: MDI in v1 limited to FC/FM = 0.02: the carrier FC = 20 Hz is below the modulation
FM = 1000 Hz (SFFM reads VO VA FC MDI FM; the manual's general form shows FM MDI FC)
```

A clamp with the carrier above its modulation (an MDI asked above FC/FM) prints the old line.

## The checks

`sffmdefault_examples` (new), under both solvers, each source as V and as I into 1 Ω:
- **[1]** `SFFM(0 1)` over 1 ms: carrier 500 kHz, modulation 5 kHz, MDI 90, within 1e-8 of the
  manual's equation at every point, I = V (E-911: off by 2.0).
- **[1]** ... with no MDI warning (E-911: the clamp warning).
- **[2]** `SFFM(0 1 1meg)`: the modulation defaults to 5 kHz, MDI 90 unclamped, no warning.
- **[3]** The manual's SFFM example: the warning names the 20 Hz carrier below the 1000 Hz
  modulation, and the order SFFM reads.
- **[4]** The sources section's example `SFFM(0 1 10K 5 1K)`: no warning, the waveform at every
  point.
- **[5]** Control: `SFFM(0 1 1meg 2 100k)` written in full, unchanged.

## Limits

- **The manual.** It is upstream's PDF, and its general-form line and SFFM example still show
  FM MDI FC.
- **The warning.** It is printed once per ngspice session for each source type, as before, so a
  second source that clamps says nothing.
