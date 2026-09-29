# evtedge_examples — crossing edges and small-signal `transition`/`slew` (Enhancement-587), and the landing of the step on a crossing (Enhancement-759)

```
python3 verify_evtedge.py
```

24 checks, both solvers (18 of 24 on the E-757 toolchain).

## The need

Two findings of the 2026-09-07 hunt:

- `@(cross(e, +1))` and `@(above(e))` counted `prev <= 0 && cur > 0`, so an
  expression that **starts exactly at zero** — a sine whose offset equals the
  threshold — fired on the first step after t = 0, and `above` fired again on
  the t = 0 Newton walk of a transient. Off by one whenever a source starts on
  the threshold.
- `V(o) <+ transition(V(in))` showed −0.036° at 100 kHz and −3.6° at 10 MHz in
  `ac`: the tracking loop's linearisation is a lag with τ = t_rise/1000 — 1 ns
  for the default transition and for an instantaneous one. The LRM's
  small-signal transfer of `transition()` and of a `slew()` that is not slewing
  is unity.

## What changed

- A crossing needs a previous sample on the **other** side: strict on the
  previous side, inclusive on the current one. An expression that lands exactly
  on zero from below fires once, at that sample, and not again. `above` gates
  its edge at t = 0 of a transient the way `cross` always has, keeping its LRM
  initialization event (positive at the initial step) and every edge in dc sweeps.
- The tracking loop's reactive residual is zeroed for the `ac` and `noise`
  evaluations only, which turns the equation into `y = x` exactly. DC and
  transient, where the loop does its work, are untouched; a `td` delay is still
  honoured to the degree.

| check | result |
|---|---|
| sine on the threshold | 2 rising, 2 falling, 4 either, 2 above over 2.5 periods (was 3/2/5/3) |
| just above / just below | 2/2/4/3 (above adds its initialization event) and 3/3/6/3 |
| triangle landing on the threshold | once per pass |
| dc sweep | `above` counts the pass, `cross` nothing (transient-only) |
| `transition()`, `transition(x,0,0,0)`, `slew()` in ac | phase 0, magnitude 1 at 100 kHz, 1 MHz, 10 MHz |
| `transition(x, 5u, 1u)` | exactly −180° at 100 kHz |
| noise | unity transfer through `transition` |
| transient | the 1 µs ramp and the 1 V/µs slew as before |

## Enhancement-759: the step lands on the crossing

`evtland.va` is a compiled switch whose event bodies record when they ran (`trise`,
`tfall`, `tabove`, the counters, a `$strobe`), and `landdisc` the same switch with a
`$discontinuity(0)` in the body. A crossing used to be resolved to the step grid: on a
0→1→0 V ramp over 2 µs at a 100 ns step the switch closed 31.2 ns late, the same as a
plain `if` and as the built-in `sw`, and `time_tol` was ignored. Now the event asks
ngspice to redo the step at the interpolated crossing (plus `time_tol`, or a thousandth
of the step) and the body runs there.

| check [9] | result |
|---|---|
| the rising, falling and `above` bodies' `$abstime` | 500.04 ns, 1500.00 ns, 500.04 ns for crossings at 500 and 1500 ns |
| the first output point on the new side | at the landing (was 31.2 ns late) |
| a `$strobe` in the body | printed once per crossing, with the crossing time |
| `time_tol = 1p` | the bodies within 2 ps (500.001 ns) |
| the 500 MHz pulse drive at a 1 ns step over 2 µs | exactly 1000 / 1000 / 2000 (was 1001 / 1001 / 2002) |
| `$discontinuity(0)` in the body | the landing kept, the eighth is the step after it (75 points, 3 rejected; an interim build looped at 126 and 23) |
