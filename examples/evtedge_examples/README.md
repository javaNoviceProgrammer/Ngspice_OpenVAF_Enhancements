# evtedge_examples — crossing edges and small-signal `transition`/`slew` (Enhancement-587)

```
python3 verify_evtedge.py
```

14 checks, both solvers.

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
