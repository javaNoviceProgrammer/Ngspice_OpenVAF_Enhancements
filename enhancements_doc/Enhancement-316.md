# Enhancement-316 — ngspice: `.meas AVG` ended one timestep short of `to`

Found by continuing to oracle-check `.meas` against its own contract (the E-302/303/304 family):
`AVG` is the same quantity as `INTEG/(to−from)` computed over the identical window. On a signal
whose window end coincides (within 100 ULPs) with a sample, they disagreed by ~1.6 %.

## The bug

`measure_minMaxAvg()`'s final window-clip (added in Enhancement-302, which made `AVG` integrate a
trapezoid over `[from, to]`) guarded the **whole accumulation** with
`!AlmostEqualUlps(svalue, meas->m_to, 100)`:

```c
if (mFunctionType == AT_AVG && first != 0 && i > 0 &&
        !AlmostEqualUlps(svalue, meas->m_to, 100)) {
    /* interpolate to `to` and add the final trapezoid */
}
break;
```

When the first out-of-window sample fell within 100 ULPs of `to`, `!AlmostEqualUlps` was false, so
the entire final trapezoid `[sprev, to]` — a full timestep — was skipped. AVG's window then ended
one timestep short of `to`. Empirically, for a 2.5e-7 timestep the AVG window echoed
`to = 6.45990e-04` while INTEG (correct) echoed `to = 6.46240e-04` — exactly 2.5e-7 apart — so
`AVG != INTEG/(to−from)`.

`measure_rms_integral()` (INTEG/RMS) does **not** have this problem: it always adds the final
point, interpolating to `to` only when the sample overshoots, else using the ≈`to` sample as-is.

## The fix

Move the `!AlmostEqualUlps` guard so it gates only the *interpolation*, not the *accumulation* —
matching INTEG. The final trapezoid is now always added: interpolate to `to` when the sample is
more than 100 ULPs beyond it, otherwise use it as-is. AVG now covers the full `[from, to]` window
and `AVG == INTEG/(to−from)` (rel 1.6e-6 on the reproducer). MIN/MAX keep their whole-sample
semantics (unaffected — the branch is `AT_AVG`-only).

## Verification

`examples/measavgwin_examples/verify_measavgwin.py` — AVG equals INTEG/(to−from) over the same
window and AVG's echoed window reaches `to`; both **fail on the pre-fix binary**. The E-302/303/304
suite (`measwindow`, 44 checks) and E-311 (`measparam`) still pass under both solvers, and the full
example regression is green.

## Scope of change

`src/frontend/com_measure2.c`, `measure_minMaxAvg()` `AT_AVG` window-clip only.
