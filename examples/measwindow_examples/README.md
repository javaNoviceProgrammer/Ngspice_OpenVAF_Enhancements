# measwindow_examples — Enhancements 302 / 303 / 304

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

## dc — Enhancement-303

E-302 covered time/frequency scales only. `dc` was excluded because a sweep may **descend**
(`dc v1 2 0 -0.001`) and enters its window at the HIGH end, where an unguarded clip
extrapolates. E-303 completes it: the clip works from the **actual crossing** between the
previous raw sample and the current one, which is direction-agnostic.

| sweep, window `0.25 -> 0.75` | before | after | closed form |
|---|---|---|---|
| `dc v1 0 2 0.001` (ascending) | 0.270250 | 0.270832 | 0.2708333 |
| `dc v1 2 0 -0.001` (descending) | 0.270250 | 0.270832 | 0.2708333 |

(oracle: `v(a)=v(in)^2`, so the mean over `[p,q]` is `(q^3-p^3)/(3(q-p))`.)

## descending `integ` / `rms` — Enhancement-304

On a **descending** sweep, `.meas dc integ` and `rms` used to return `0.0` with `from= nan`
(or print nothing). `measure_rms_integral()` met the first sample already above `to`,
interpolated it against index `i-1 == -1` and broke with a one-element array, so the
integration sums ran zero times. That index was a real **heap-buffer-overflow**:

```
ERROR: AddressSanitizer: heap-buffer-overflow
    #0 measure_interpolate   com_measure2.c:195
    #1 measure_rms_integral  com_measure2.c:1415
```

It now walks the samples in order of increasing scale (the identity for ascending data), and
the bounds guard is the traversal position rather than the raw index.

| descending, window `0.25 -> 0.75` | before | after | closed form |
|---|---|---|---|
| `integ` | 0.0 (`from= nan`) | 0.135416 | 0.135416667 |
| `rms` | *no output* | 0.307458 | 0.307459347 |

## Verify

```bash
python3 verify_measwindow.py
```

Runs under both linear solvers (44 checks). It scores 14/28 on the pre-302 binary,
32/38 on the pre-303 one and 40/44 on the pre-304 one, so each set of checks is a real
regression guard rather than a vacuous one.
