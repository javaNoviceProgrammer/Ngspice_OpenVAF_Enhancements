# measwindow_examples — Enhancement-302

`.meas ... avg` did not clip its window to `[from, to]`.

It accumulated a trapezoid only over the **samples that fell inside** the window and
divided by their span, without interpolating either boundary. `rms` and `integ` — the same
quantity family, in `measure_rms_integral()` — already clip to the exact boundaries. So
ngspice's own two answers for the same window disagreed:

```
.meas tran i1 integ v(a) from=0 to=250u   ->  3.18310e-04   to=2.50000e-04
.meas tran a1 avg   v(a) from=0 to=250u   ->  1.27114e+00   to=2.50280e-04   <- overshot
```

`integ/(to-from)` = 1.27324, and the closed form is 1.2732395. The echoed `to=` gave it
away: **AVG reported the first sample OUTSIDE the window**, a time the average never
covered.

| window | avg before | avg after | closed form |
|---|---|---|---|
| 0 → 250 µs | 1.27114 | 1.27324 | 1.2732395 |
| 3.7 µs → 246.3 µs | 1.28411 | 1.28122 | 1.2812223 |
| 6.28 µs → 493.72 µs | 1.30864 | 1.30503 | 1.3050309 |
| 0.5 µs → 999.5 µs (full period) | 6.8e-07 | 6.2e-12 | 0 |

The error is O(dt/window): ~1.6e-3 relative here with 250 steps in the window, and larger
on a coarser run. `integ` and `rms` were already exact (~3e-7) and are unchanged.

## How it was found

A closed-form oracle, not a comparison against a previous build — a same-binary comparison
cannot see an error that is uniformly present. Every expected value is the analytic
integral of the sine:

```
integ(t0,t1) = (A/w)*(cos(w t0) - cos(w t1))     avg = integ/(t1-t0)
```

The windows deliberately land **between** samples so both boundaries need interpolation.

## Scope — what is NOT fixed

The fix applies to **time/frequency scales** (`tran`, `ac`, `sp`), which ascend
monotonically. A `dc` sweep may descend (`dc v1 2 0 -0.001`) and enters its window at the
high end, where forcing the first point to `from` would extrapolate outside the bracketing
samples. The `dc` path is therefore **left untouched** and every `dc` measurement is
byte-identical to before.

`.meas dc avg` still truncates the same way — measured, on an ascending sweep with data
available beyond both ends:

```
dc v1 0 2 0.001;  meas dc avg v(a) from=0.25 to=0.75   ->  0.270250   to=7.49000e-01
                  closed form (mean of x^2)            ->  0.2708333
```

(`.meas dc integ` over that window is correct: 1.35416e-01 vs 0.135416667.) Two further
pre-existing `dc` problems turned up while scoping this and are **not** addressed here: on
a *descending* sweep `integ` returns `0.0` with `from= nan`, and `avg` echoes a meaningless
`to=`.

## Verify

```bash
python3 verify_measwindow.py
```

Runs under both linear solvers (28 checks). It fails 14/28 on the pre-fix binary, so it is
a real regression guard rather than a vacuous one.
