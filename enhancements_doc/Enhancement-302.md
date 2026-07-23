# Enhancement-302 — ngspice: `.meas avg` clips its window to `[from, to]`

`.meas ... avg` did not clip its averaging window to the requested `[from, to]`. It
accumulated a trapezoid over only the **samples that fell inside** the window and divided
by their span, without interpolating either boundary — so the first and last partial
intervals were silently dropped.

`rms` and `integ`, the same quantity family (in `measure_rms_integral()`), already clip to
the exact boundaries. The result was that **ngspice's own two answers for the same window
disagreed**:

```
.meas tran i1 integ v(a) from=0 to=250u   ->  3.18310e-04   to=2.50000e-04
.meas tran a1 avg   v(a) from=0 to=250u   ->  1.27114e+00   to=2.50280e-04
```

`integ/(to-from)` = 1.27324; the closed form is 1.2732395. The echoed `to=` is the tell:
AVG reported `2.50280e-04` — the first sample **outside** the window, a time the average
never covered.

## The defect

In `measure_minMaxAvg()` (`src/frontend/com_measure2.c`) the loop was:

```c
if (svalue < meas->m_from) continue;                       /* skip before the window */
if (meas->m_to != 0.0 && svalue > meas->m_to) break;       /* stop after it          */
...
mValue += 0.5 * (value + pvalue) * (svalue - sprev);       /* trapezoid, INCLUDED pts */
Tsum   += (svalue - sprev);
...
meas->m_measured    = mValue / Tsum;
meas->m_measured_at = svalue;                              /* the breaking sample     */
```

so the effective window was `[first sample >= from, last sample <= to]`, up to one
timestep short at each end. The error is `O(dt/window)`.

## The fix

Clip both ends by interpolating to the exact boundary — the same thing
`measure_rms_integral()` does for RMS and INTEG — and report the true window end:

* on crossing `to`: interpolate the value at `m_to`, accumulate that final trapezoid, then
  stop;
* on entering at `from`: interpolate the value at `m_from` and start there;
* `m_measured_at` becomes `sprev` (the last point actually accumulated).

All three are guarded to `AT_AVG`, so `min` / `max` / `min_at` / `max_at` keep their
whole-sample semantics unchanged.

| window | before | after | closed form |
|---|---|---|---|
| 0 → 250 µs | 1.27114 | 1.27324 | 1.2732395 |
| 3.7 µs → 246.3 µs | 1.28411 | 1.28122 | 1.2812223 |
| 6.28 µs → 493.72 µs | 1.30864 | 1.30503 | 1.3050309 |
| 0.5 µs → 999.5 µs (full period) | 6.8e-07 | 6.2e-12 | 0 |

Relative error drops from ~1.6e-3 to ~4e-7 — `avg` now equals `integ/(to-from)` to the
same precision `integ` itself achieves.

## Scope — the `dc` path is deliberately untouched

> **Superseded in part:** [Enhancement-303](Enhancement-303.md) completes this for `dc`, in
> both sweep directions. The remaining `integ`-on-a-descending-sweep defect noted below is
> still open.

The fix applies to **time/frequency scales** (`tran`, `ac`, `sp`), which ascend
monotonically. A `dc` sweep may descend (`dc v1 2 0 -0.001`) and enters its window at the
HIGH end; an unguarded boundary clip there extrapolates far outside the bracketing samples
and poisons every later trapezoid. (This was caught during development: an early version
of this fix turned a descending-sweep `avg` of 0.270250 into `-3.79e+11`.) The `dc` branch
is therefore excluded, and **every `dc` measurement is byte-identical to before.**

`.meas dc avg` still truncates the same way — on an ascending sweep with data available
past both ends, `from=0.25 to=0.75` gives 0.270250 (echoing `to=7.49000e-01`) against a
closed form of 0.2708333, while `.meas dc integ` over the same window is correct. Two
further pre-existing `dc` problems were observed and are not addressed here: on a
descending sweep `integ` returns `0.0` with `from= nan`, and `avg` echoes a meaningless
`to=`.

## Verification

`examples/measwindow_examples/verify_measwindow.py` — 28 checks under both solvers,
against closed-form integrals of the sine (never against a previous build; a same-binary
comparison cannot see a uniformly present error). Windows deliberately land **between**
samples so both boundaries require interpolation. The suite fails **14/28 on the pre-fix
binary**, so it is a real regression guard. `integ`, `rms`, `min`, `max` and `pp` are
asserted unchanged.

## Scope of change

`src/frontend/com_measure2.c`, one function.
