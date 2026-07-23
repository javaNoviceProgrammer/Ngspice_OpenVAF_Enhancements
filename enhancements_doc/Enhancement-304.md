# Enhancement-304 — ngspice: `.meas dc integ`/`rms` out-of-bounds read on a descending sweep

On a **descending** dc sweep (`dc v1 2 0 -0.001`), `.meas dc integ` and `.meas dc rms`
returned `0.0` with `from= nan` — or printed nothing at all — and did so by reading off the
front of the data array.

```
dc v1 2 0 -0.001
meas dc e1 integ v(a) from=0.25 to=0.75   ->  0.00000e+00 from= nan to= 7.50000e-01
meas dc r1 rms   v(a) from=0.25 to=0.75   ->  (no output)
```

## The defect

`measure_rms_integral()` builds a clipped copy of the data over `[from, to]` and assumes the
scale **ascends** — it clips at `from` on the way in and at `to` on the way out, and the
segment widths `x[i+1]-x[i]` it feeds to the Simpson / trapezoid sums must come out positive.

A descending sweep starts at the top, so the very first sample (`2.0`) is already above
`to` (`0.75`). The end-clip fired immediately on `i == 0` and interpolated against index
`i-1`:

```c
value = measure_interpolate(xScale, d, i-1, i, meas->m_to, 'y', meas);   /* i-1 == -1 */
```

`measure_interpolate` then read `values->v_realdata[-1]` and `xScale->v_realdata[-1]`.
AddressSanitizer flags it precisely:

```
ERROR: AddressSanitizer: heap-buffer-overflow
    #0 measure_interpolate   com_measure2.c:195
    #1 measure_rms_integral  com_measure2.c:1415
```

It then `break`s with a one-element array, so the integration loop (`while (i < xy_size-1)`)
ran **zero** times and the sums stayed 0 — while `first` was never set, leaving
`m_measured_at` unwritten, which is the `from= nan`.

## The fix

Walk the samples **in order of increasing scale** rather than index order. For ascending data
(all `tran`, all `ac`, and an ascending sweep) this is the identity and every step below is
untouched; for a descending sweep it presents the same ascending view the rest of the function
already expects.

The bounds guard comes with it: the "is there a previous sample" test is now the traversal
position `n > 0` rather than `i > 0`, which is correct in both directions — that is exactly
the guard the old `i-1` lacked. With no preceding sample there is nothing to interpolate
against, so the window simply has not been entered yet.

| measurement, window `0.25 → 0.75`, descending | before | after | closed form |
|---|---|---|---|
| `integ` | 0.0 (`from= nan`) | **0.135416** | 0.135416667 |
| `rms` | *no output* | **0.307458** | 0.307459347 |
| `avg` (already fixed in E-303) | 0.270832 | 0.270832 | 0.2708333 |

Two dead reads went with it. The `if (toVal < 0.0)` tail indexed `d->v_realdata[i]` with the
*integration* loop's counter — past the end of the data — into variables nothing reads again,
and took the window end from `xScale->...[v_length-1]`, which is the SMALLEST scale value when
the sweep descends rather than the last one traversed. The end of the window is simply the
last point appended.

## Verification

`examples/measwindow_examples/verify_measwindow.py` — 44 checks under both solvers. The dc
section runs the same window in **both sweep directions** for `avg`, `integ` and `rms` against
closed forms (`∫x²`, `mean x²`, `rms x²`), and checks the echoed window. The suite scores
**40/44 on the pre-fix binary** (which already has E-302 and E-303).

The out-of-bounds read itself is proven gone rather than argued: the same deck under an
AddressSanitizer build reports `heap-buffer-overflow` at `com_measure2.c:195` before the fix
and is clean after. `tran` and `ac` measurements are byte-identical, as the ascending path is
unchanged. Full sweep 239/239 OK.

## Scope of change

`src/frontend/com_measure2.c`, `measure_rms_integral()` only.
