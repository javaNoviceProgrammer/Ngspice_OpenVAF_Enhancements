# Enhancement-207 — eye diagram / jitter analysis (`eye`)

A new application domain: the core measurement for serial links / SerDes / high-speed
I/O. The `eye` command folds a received data waveform modulo the unit interval and
reports the standard signal-integrity metrics — jitter, eye height/width, and the eye
opening at a target BER.

## Command

```
eye <expr> -ui <T> [-tstart <t0>] [-threshold <vth>] [-window <frac>]
```

Front-end post-processing over a transient result vector (solver-independent), in the
family of `fft` / `linearize` / `meas`. Given the data signal `<expr>` and its unit
interval `-ui <T>`, it:

1. **Rails + threshold** — the 20th/80th percentiles of the samples give `level0` /
   `level1`; the decision threshold defaults to their midpoint (or `-threshold`).
2. **Crossings** — every threshold crossing is found by linear interpolation.
3. **Jitter** — the UI phase is the circular mean of the crossings mod UI; each
   crossing's **TIE** (time-interval error, relative to the ideal UI grid) gives
   **jitter RMS** (std of TIE) and **peak-to-peak**.
4. **Eye height** — the vertical opening at the sampling instant (UI/2 from the
   transitions): `min(high samples) − max(low samples)` in a ±`window`·UI slice.
5. **Eye width** — `UI − jitter_pp` at the threshold, plus the width at **BER 1e-12**
   from the Gaussian random-jitter tail (`UI − 14.069·jitter_rms`).
6. **Folded eye** — the waveform folded modulo 2·UI into `eye_wave` vs `eye_t`; the
   scatter plot of those two vectors *is* the eye diagram (`plot eye_wave vs eye_t`).

Results are published as permanent vectors (`eye_height`, `eye_width`,
`eye_width_ber12`, `eye_jitter_rms`, `eye_jitter_pp`, `eye_level0/1`, `eye_amplitude`,
`eye_threshold`, `eye_crossings`, `eye_ui`).

## Implementation

New self-contained front-end command `com_eye.c` (+ `com_eye.h`), registered in
`commands.c` / `com_commands.h` / `Makefile.am`. It reads the vector and its time
scale via `ft_evaluate`, and creates the folded-eye vectors with `dvec_alloc` /
`vec_new` (as `stb`/`sweep` do). No numerical-core changes.

## Verification

Signals with **known** metrics (`examples/eye_examples`):

- **[clean]** an ideal 0/1 clock (perfectly periodic edges) recovers rails [0, 1] and
  amplitude 1, with jitter ~1e-24 s (machine zero) and a full-UI, fully-open eye.
- **[jitter]** a clock whose edges carry a **known injected Gaussian jitter**
  (σ = 20 ps): the reported `eye_jitter_rms` / `_pp` match the injected values to a
  few percent (≈ 18.6 ps rms / 99 ps pp), and `eye_width` equals `UI − jitter_pp`.
- **[vectors]** the folded eye (`eye_wave` vs `eye_t`) and the scalar result vectors
  are published.

## Scope

Front-end only; solver-independent. A post-processing command — it consumes whatever
transient waveform is in the current plot, so it works on built-in-device, OSDI, and
behavioral signals alike.
