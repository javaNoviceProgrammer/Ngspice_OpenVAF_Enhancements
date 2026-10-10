# Enhancement-848: AVG, INTEG and RMS with `from=` keep the first sample in the window — the value at `from` overwrote it, and the sum ran from `from` straight to the second sample

**Scope:** F4 of the
[second robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).
F5, at the start of a WHEN window, is [Enhancement-849](Enhancement-849.md).

ngspice: `frontend/com_measure2.c`, `measure_minMaxAvg` (AVG) and `measure_rms_integral`
(INTEG, RMS).

`examples/measstart_examples/` (new), with Enhancement-849. **ngspice only.**

**Suites:**
- [`measstart_examples`](../examples/measstart_examples/): 18 of 18 per solver. On the E-844
  binaries the three checks of this defect, [1] and [2], fail; [3] is a control.
- The campaign's Family C (300 random decks, 3 600 measurements against a reference computed
  from the same samples): every AVG now matches, against 96 windowed AVGs off by up to 4.8 % on
  E-847, and so does every INTEG of a piecewise-linear source. The INTEGs and RMSs that still
  differ all match a model of ngspice's quadrature to 1e-9: that is F11.
- The full sweep: 554 of 554.

## What was wrong

```spice
v1 1 0 pwl(0 0 1u 1 2u 0)
r1 1 0 1k
.meas tran a1 avg v(1) from=0.97u to=1.5u
.meas tran i1 integ v(1) from=0.97u to=1.5u
.tran 0.1u 2u
```

The first sample inside the window is the corner at 1 µs. `a1` was 0.7630755 and `i1`
4.04430e-7, where the waveform's own values are 0.7633019 and 4.04550e-7. Without `from=`, both
were exact.

[Enhancement-302](Enhancement-302.md) made AVG start at exactly `from` by interpolating there.
It did so by overwriting the first in-window sample's value and time, so that sample never
entered the sum, and the trapezoid ran from `from` straight to the second sample.
`measure_rms_integral` did the same for INTEG and RMS. The error is the area between the
waveform and that chord: nothing on a straight segment, and most at a corner or on a curve. In
the campaign's Family C it reached 4.8 % on a sampled sine and 0.11 % on an RC response.

## The change

The value at `from` is a point of its own, ahead of the first sample:
- AVG opens its sum with the trapezoid from `from` to that sample;
- INTEG and RMS put the point into the arrays they integrate, before the sample.

The arrays are sized for the samples of the data vector. The point at `from` replaces a sample
before the window, which needs at least one, so they still hold every point.

When `from` falls within 100 ULPs of a sample, the sample opens the window, as before. A dc
sweep keeps E-303's direction-agnostic AVG clip, which already kept the sample.

## The checks

`measstart_examples`:
- **[1]** AVG and INTEG over a window opening just before the corner of a triangle: exact.
- **[2]** RMS of a ramp-then-flat over that window: the trapezoid of the square on the ramp,
  exact on the flat part.
- **[3]** (control) `from` on the corner sample, and AVG without a window.

The checks place `from` between two samples of a first run, so they do not depend on where the
timestep control puts the samples.
