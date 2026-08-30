# Enhancement-512 — `transition` reached its final value only for slow edges

```
python3 verify_transedge.py
```

14 checks, both linear solvers, spanning five decades of rise time.

## What was wrong

`transition` and `slew` are one rate-limited tracking loop,
`dy/dt = clamp(K·(x−y), −1/tfall, +1/trise)`. While the clamp is saturated that is
an exact linear ramp at the LRM's rate; it releases once the remaining gap falls
below `rate/K`, and the rest of the swing is a first-order tail with τ = 1/K.
**`K` was a fixed 1e9 s⁻¹**, so the gap was `1/(K·trise)` — it depended on how
fast the edge was:

| `trise` | linear part | value at delay + trise (LRM: 1.0) |
|---:|---:|---:|
| 3 ns | 66.7% | **0.8774** |
| 30 ns | 96.7% | 0.9873 |
| 3 µs | ~100% | 1.000039 |

The shortfall is `e⁻¹/(K·trise)` — 0.877382 measured against 0.877374 predicted at
3 ns. Refining the timestep 100× converged to 0.8776, i.e. to the *wrong* value.

## The fix

`K = TRACK_C · rate`, so the released gap is `1/TRACK_C` at every speed.
`TRACK_C = 1e3` **by measurement**: the gap also bounds the integrator's
truncation error at the ramp's corner, so raising it makes
[Enhancement-47](../../enhancements_doc/Enhancement-47.md)'s plateau check worse
(0.875 → 0.874940 → 0.874766 at 1e3/1e4/1e5).

Preserved: an instantaneous edge (`trise ≤ 0`, clamped to 0 by
[E-504](../../enhancements_doc/Enhancement-504.md), reciprocal `+inf`) keeps the
old fixed gain, because `inf · 0.0` is NaN. And the gain comes from the *faster*
of the two rates — a per-direction gain made the loop jump at the crossing point
and overshoot to 1.01.

## Why it survived

`defaulttransition` pins the 1 µs case, deep inside the region where the old code
was already right — the same blind spot as
[E-510](../../enhancements_doc/Enhancement-510.md), where the suite tested
`$ln1p(0.5)` and a literal folds before code generation.

## Files

| file | what it holds |
|---|---|
| `tedge.va` | `transition` and `slew` with the rise time as a parameter |
