# Enhancement-892: a fourier window the run spans exactly is analysed — 12 of 800 runs read "longer than time span", and `.four` then said there was no transient data

**Scope:** D1 of the
[nonlinear correctness campaign of 2026-10-15](../docs/bug_hunts/2026-10-15_ngspice-openvaf-r-nonlinear-correctness-campaign.md).

ngspice:
- `frontend/fourier.c`: a window short of the data by no more than its first interval is
  analysed, and a refusal gives the numbers.
- `frontend/dotcards.c`: the `.four` route says "No transient data available" only when there is
  none.

`examples/nlnotes_examples/` is new, shared with [E-893](Enhancement-893.md) and
[E-894](Enhancement-894.md). **ngspice only.**

**Suites:**
- [`nlnotes_examples`](../examples/nlnotes_examples/): [1] to [3] are this enhancement's, 11 of
  11 per solver. On the E-888 binaries [1] to [3] fail.
- The suites that use `fourier` and `.four` pass.
- The full sweep: 591 of 591.

## What was wrong

`fourier` (and `.four`) analyses the last `nperiods` periods of the run. With `polydegree` set, it
refused when the data spanned less than that window. A run from one period to three, analysed over
two, spans the window exactly, yet 12 of the campaign's 800 runs were refused:

```
Error: (2 * wavelength) longer than time span
No transient data available for fourier analysis
```

The campaign took this for rounding. It is not. A run with `tstart` saves from its first accepted
point after `tstart`, not at it. In seed 1009 that point came 0.28 of a step late, so the data was
short of the window by 7e-5 of it. The second line came from the `.four` route, which printed it
after any refusal. It contradicted the reason above it: there was transient data.

## The change

A window short of the data by no more than the data's first interval is the window asked for. It
starts before the first point by less than one step, and the interpolation's first polynomial
reaches it as accurately as it reaches the points between.

A window really longer than the data is still refused, now with the numbers:

```
Error: 2 periods of 182.535 Hz (0.0109568 s) are longer than the time span of the data (0.00822084 s)
```

The `.four` route prints "No transient data available for fourier analysis" only when there is no
transient plot. `fourier` has said why it refused anything else.

## The checks

`nlnotes_examples`:
- **[1]** Family F's seed 1009, a `.four` over the last 2 of 3 periods: every harmonic is within
  2e-3 of the exact one (4e-6 measured), and there is no "No transient data" line.
- **[2]** Seed 1013 through the `fourier` command at `polydegree=3`: the fundamental and the 6th
  harmonic as exact.
- **[3]** A window really longer than the data is refused with the numbers, and the `.four` route
  adds nothing after the reason.

All 12 refused runs are analysed, and agree with the exact harmonics within the interpolation's
accuracy.
