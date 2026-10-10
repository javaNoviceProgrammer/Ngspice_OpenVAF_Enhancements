# Enhancement-849: a WHEN window opens at its TD, FROM or TO — a crossing between its first two samples was lost, and with several crossings the next one was reported

**Scope:** F5 of the
[second robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md),
after [Enhancement-848](Enhancement-848.md).

ngspice: `frontend/com_measure2.c`, `com_measure_when`, which WHEN, FIND..WHEN and TRIG/TARG
share. Two helpers, `when_value` and `when_scale`, read a sample the way its loop does.

`examples/measstart_examples/` (new), with Enhancement-848. **ngspice only.**

**Suites:**
- [`measstart_examples`](../examples/measstart_examples/): 18 of 18 per solver. On the E-844
  binaries the 11 checks of this defect, [4] to [9], fail. [10], [11] and the second check of
  [5] are controls.
- The campaign's Family C: its two WHEN and FIND..WHEN mismatches are gone.
- The full sweep: 554 of 554.

## What was wrong

```spice
v1 1 0 pwl(0 0 1u 1)
r1 1 0 1k
.meas tran w0 when v(1)=0.55 rise=1
.meas tran w1 when v(1)=0.55 rise=1 td=0.45u
.meas tran w2 when v(1)=0.55 rise=1 td=0.35u
.tran 0.1u 1u 0 0.1u
```

`w0` and `w2` are 0.55 µs, but `w1` failed "out of interval". The only crossing lies between the
first two samples after TD, at 0.5024 µs and 0.6024 µs.

`com_measure_when` uses a window's first sample only to remember a value. It uses the second to
classify the side of the threshold, without counting a crossing, and evaluates from the third.
[Enhancement-418](Enhancement-418.md) made that deliberate for the start of the data: the
interval from sample 0 runs from the operating point, and a model can straddle a threshold there
for reasons that are not the waveform's. After TD, both samples are real, and a crossing between
them was lost. With several crossings the next one was reported: Family C's
`when v(c)=0.341 fall=1 td=0.465` gave 0.614 where the samples cross at 0.477.

The same loss affected:
- FIND..WHEN and TRIG/TARG with TD, which call the same function;
- WHEN with FROM;
- ac and dc sweeps entering their window through FROM, or a falling dc sweep through TO.

A crossing between the last sample before TD and the first after it, at a time past TD, was lost
too.

## The change

A window whose first sample comes after sample 1 starts at its TD, FROM or TO. The boundary's value
is interpolated from the samples on either side, and the side of the threshold is classified
there. The interval from the boundary to the first sample in the window is evaluated at once, so
a crossing past the boundary counts and one before it does not.

The rule at the start of the data is unchanged: the interval from sample 0 is still not
evaluated. When the window opens on sample 1, or on a sample within 100 ULPs of the boundary,
that sample classifies the side, and evaluation starts with the next interval.

At the restart of a nested dc sweep, Enhancement-418's reset applies as before. The sample before
the restart belongs to the previous sweep, and nothing is interpolated across it.

## The checks

`measstart_examples`:
- **[4]** WHEN `td=` with the crossing between the first two samples after TD.
- **[5]** A crossing past TD, before the first sample after it, is found. (control) A crossing
  before TD is not counted.
- **[6]** FIND..WHEN, TRIG/TARG, a two-vector WHEN with that TD, and WHEN `from=`.
- **[7]** `fall=1 td=` with the first fall after TD in the first interval: on E-844 the next
  fall, 0.4 µs later, was reported.
- **[8]** ac: WHEN `from=` on a low-pass.
- **[9]** dc: `from=` on a rising sweep, `to=` on a falling one, and `from=` on nested sweeps.
- **[10]** (control) Nested dc sweeps: `rise=2` is the second sweep's crossing, with and
  without `to=`.
- **[11]** (control) WHEN without `td`, and with a `td` well before the crossing.

The checks place TD and FROM from the samples of a first run.
