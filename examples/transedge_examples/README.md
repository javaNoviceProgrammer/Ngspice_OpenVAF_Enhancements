# Enhancement-512 — `transition` reached its final value only for slow edges

```
python3 verify_transedge.py
```

26 checks, both linear solvers, spanning five decades of rise time.

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
| `tramp.va` | E-698: a comparator through `transition` (or `slew`) with the swing, the times and a switched capacitance as parameters |

Since E-697 (hunt F7 of 2026-09-21) a side whose rate is at or above 1e12 V/s
takes the infinite-rate path (no clamp, the fixed 1e9/s gain) instead of a ramp
the timestep control cannot resolve: a `slew` at 1e13 V/s aborted the transient
at its first edge ("Timestep too small"), as did every rate up to 1e297; three
checks pin 1e13, 1e30 and a 0.1 ps `transition` rise.

## Enhancement-698: the operators are the simulator's

Since [E-698](../../enhancements_doc/Enhancement-698.md) (hunt F1 and F2 of
2026-09-21) neither operator is a tracking loop any more. The compiled model
emits the synthetic input node `V(y) = expr` and stores the operator's
arguments in instance data; ngspice schedules `transition`'s ramps from the
changes of the *accepted* input (LRM 4.5.8, corners as breakpoints, the
interrupted-transition rule of Figures 4-7 to 4-12, a queue of pending
transitions behind a delay) and stamps `slew` as the ideal limiter on the
output it accepted at the previous point (LRM 4.5.9). The loop ran at the
fixed rate `1/tr` -- a 5 V swing took 5 µs for `tr = 1u` -- and its stiff
tail rang under the trapezoidal rule whenever the edge fell inside a
timestep: the plateau read 0.99981 and `ddt` of it a current that was not
there. Nine checks pin the new behaviour: four swings (1, 5, 0.2, −3 V) half
way at 0.5 µs and complete at 1 µs on both edges with plateaus exact to 1e-9
at a 10 µs step under trap; `ddt(1n · transition)` reading 1 mA on the edge
and 0 on the plateau; `slew` of the comparator with exact plateaus and no
overshoot; the interrupted 0 → 2 ramp at 1.0 when reversed and back at 0 in
half the fall time; and a sine through `transition` finishing (it used to
breed a breakpoint per timepoint). The E-512 and E-697 checks above are
unchanged, and still pass: the endpoint is exact at every speed and a rate
at or above 1e12 V/s is simply a rate the limiter never has to enforce.
