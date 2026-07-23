# Enhancement-303 — ngspice: `.meas dc avg` clips its window too, in either sweep direction

Enhancement-302 fixed `.meas avg` for **time and frequency** scales (`tran`, `ac`, `sp`) but
deliberately excluded `dc`, because a dc sweep may **descend** (`dc v1 2 0 -0.001`) and enters
its window at the HIGH end — an unguarded clip there extrapolates outside the bracketing
samples. This completes the fix for `dc`, in both sweep directions.

## What was wrong

`.meas dc avg` averaged over `[first sweep point inside the window, last one inside]`, not
over the requested `[from, to]` — the same O(step) truncation, with data available on both
sides:

```
dc v1 0 2 0.001
meas dc q1 avg   v(a) from=0.25 to=0.75   ->  0.270250   to=7.49000e-01
meas dc q2 integ v(a) from=0.25 to=0.75   ->  0.135416   to=7.50000e-01   (correct)
```

With `v(a) = v(in)^2` the mean over `[p,q]` is `(q^3-p^3)/(3(q-p))` = **0.27083333**.

## The fix

Rather than assuming which bound is the "start", the clip works from the **actual crossing**
between the previous raw sample and the current one:

* previous sample outside, current inside → open the window at the exact boundary crossed;
* previous inside, current outside → close it at the exact boundary crossed, and stop.

This is direction-agnostic: it fires on an ascending sweep at `from`→`to`, on a descending
sweep at `to`→`from`, and simply never fires on a sweep that does not cross. It is guarded to
`AT_AVG`, so `min` / `max` / `min_at` / `max_at` keep their whole-sample semantics.

| sweep | before | after | closed form |
|---|---|---|---|
| `dc v1 0 2 0.001` (ascending) | 0.270250 | **0.270832** | 0.2708333 |
| `dc v1 2 0 -0.001` (descending) | 0.270250 | **0.270832** | 0.2708333 |
| `from=0 to=1`, ascending | 0.332666 | **0.333333** | 0.3333333 |

The echoed window is also corrected: it read `to=7.49000e-01` for a requested `0.75`. Because
a descending sweep finishes at the LOW bound, the reported end is the upper end of the range
actually covered, so the echo reads `from= 2.50000e-01 to= 7.50000e-01` either way rather than
the nonsensical `from= 0.25 to= 0.25`.

## Known defect NOT addressed here

> **Now fixed:** [Enhancement-304](Enhancement-304.md) resolves this, including the
> out-of-bounds read (confirmed by AddressSanitizer).

On a **descending** sweep, `.meas dc integ` (and `rms`) are still wrong — they return `0.0`
with `from= nan`. The cause is in `measure_rms_integral()`, a different function: its window
loop meets the very first sample already above `to`, interpolates it with index `i-1 == -1`
(an **out-of-bounds read**), and breaks with an empty array. `avg` no longer shares that code
path, so it is correct in both directions while `integ` is not. This is pre-existing and is
left for a separate change.

## Verification

`examples/measwindow_examples/verify_measwindow.py` — 38 checks under both solvers. The dc
section runs the **same window in both sweep directions** against the closed-form mean of
`x^2`, checks the echoed window, and asserts `min`/`max` are unchanged. The suite scores
**32/38 on the pre-fix binary** (which already has E-302), so the six dc checks are a real
guard. Full sweep 239/239 OK.

## Scope of change

`src/frontend/com_measure2.c`, `measure_minMaxAvg()` only.
