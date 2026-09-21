# Enhancement-698: `transition` and `slew` are realised by the simulator — the tracking loop ran at the fixed rate `1/rise` (a 5 V step took 5 × rise) and rang under the trapezoidal rule

**Scope:** F1 and F2 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_openvaf-r-cli-integers-transition-and-json.md).
openvaf: `hir_lower/src/lib.rs` (the `SlewInput/SlewOutput` and
`TransitionInput/TransitionOutput` equation kinds, the `TransitionDelay/Rise/Fall`
and `SlewPosRate/NegRate` places, the two slot tables), `hir_lower/src/ctx.rs`,
`hir_lower/src/expr.rs` (`lower_slew`, `lower_transition`,
`lower_transition_slot`; `lower_rate_limited_track` and its constants are gone),
`sim_back/src/context.rs`, `osdi/src/inst_data.rs`, `osdi/src/eval.rs`,
`osdi/src/lib.rs` (the `OSDI_TRANSITION_COUNTS/INFOS` and `OSDI_SLEW_COUNTS/INFOS`
tables), `osdi/header/osdi_0_4_enhancement4.h` (new, the ABI write-up).
ngspice: `src/include/ngspice/osdiitf.h`, `src/osdi/osdidefs.h`,
`osdiregistry.c`, `osdisetup.c`, `osdiload.c` (`transition_stamp`, `slew_stamp`),
`osdiaccept.c` (`transition_accept`, `slew_accept`), `osditrunc.c`, `osdiacld.c`,
`osdipzld.c`. `examples/transedge_examples/` (`tramp.va`, nine checks, 26 per
solver), `examples/lrmfilters_examples/` (the amplitude check re-pinned to the
LRM), `examples/opargs_examples/` (its ramp samples interpolated at the
instant). Handbook [§2.4](../docs/handbook/02-verilog-a-language.md) rows, the
compliance document, the `transition_examples` and `slew_examples` READMEs.
**openvaf and ngspice, a matched pair:** a `.osdi` compiled by this openvaf
needs this ngspice (its output rows are the simulator's); an older `.osdi` runs
on the new ngspice as before (its loop is compiled in).

**Suites:** [`transedge_examples`](../examples/transedge_examples/) 26 of 26 per
solver, both solvers (20 of 26 on the E-697 binaries);
[`lrmfilters_examples`](../examples/lrmfilters_examples/) 14 of 14 (13 of 14 on
the E-697 binaries); [`opargs_examples`](../examples/opargs_examples/) 16 of 16
on both (its two ramp checks read the timepoint nearest the instant, and the
corner breakpoints moved the timepoints off the print grid — 0.5072 for a
midpoint of 0.5 from a point 3.5 ns away; they interpolate at the instant now,
0.4984 new and 0.4990 old); `defaulttransition`, `tranopdelay`, `domainwarn`,
`evtedge`, `lrmops`, `lrmfuncs`, `constguard`, `limguard`, `valguard`,
`guardsweep`, `saveguard`, `hiername`, `rtdomain`, `lrmevents`, `portconnected`,
`legacygen`, `vafgvnunreach`, `vafcrash4` both solvers, unchanged; the compiler
workspace tests green apart from the three pre-existing sourcegen drift
failures; full sweep 531 of 531, run alone (two earlier sweeps read 530 of
531: opargs, above, and then rtdomain's wall-clock check [9] while the PDFs
were being built alongside it, 16 of 16 standalone).

## What was wrong

Both operators were one rate-limited tracking loop compiled into the model,
`dy/dt = clamp(K·(x − y), −neg, +pos)` (E-6, E-47, E-512, E-588, E-697), with
`transition(x, td, tr, tf)` lowered as `slew(absdelay(x, td), 1/tr, 1/tf)`.

**F1.** A loop has no memory of the swing it is asked to make, so `transition`
ran at the fixed *rate* `1/tr`: a 0 → 1 step took 1 µs for `tr = 1u`, a 0 → 5
step took 5 µs, a 0 → 0.2 step 0.2 µs, and `` `default_transition 1u ``
took 0.8 µs for 0.2 → 1 and 0.1 µs for 1 → 1.1. LRM 4.5.8: "transition()
forces all positive transitions of expr to occur over rise_time and all
negative transitions to occur in fall_time" — the time is the time, whatever
the two levels. A model switching a 3.3 V rail, a 1e-3 S conductance or a
resistance in ohms with `transition(…, 0, 10n, 10n)` got a ramp 3.3, 0.001 or
1000 times the length it wrote, and the interruption rule of Figures 4-7 to
4-12 (a 0 → 2 ramp reversed after half its 100 µs is at 1.0, and falls from
there at the original destination's slope) could not be modeled at all.

**F2.** The loop's clamp released at a gap of `rate/K` and the rest of the
swing was a first-order tail with τ = 1/K (1 ns for a 1 µs edge). When the
input stepped *inside* a timestep — a comparator in the model places no
breakpoint — the trapezoidal rule's first implicit step carried the ramp past
the target and then multiplied the error by (1 − h/2τ)/(1 + h/2τ) per step,
−0.9996 at h = 10 µs: the output settled 2e-4 off its target for the whole
plateau, above 1 or below 0, and `ddt` of it — a switched capacitor written
the textbook way, `ic = ddt(c · transition(cmp, 0, 1u, 1u))` — read up to
0.84 mA of current across a plateau where the true current is 0; in a circuit,
0.57 V on a 1 kΩ load 1.5 ms after the edge. `method=gear` was clean; `trap`
is the default.

## What changed

**The operators are the simulator's, like `absdelay`.** The compiled model
emits the synthetic input node `V(y) = expr` (a resistive residual it stamps)
and stores the operator's arguments in instance data at every evaluation —
`td`, `rise`, `fall` for a transition slot, the two rate magnitudes for a slew
slot — and the descriptor exports one record per slot
(`OsdiTransitionInfo`, `OsdiSlewInfo`; `osdi_0_4_enhancement4.h`). ngspice
allocates the `(z, y)` and `(z, z)` matrix entries next to the absdelay ones
and stamps the output row:

- **`transition`: `V(z) = ramp(t)`**, a function of time alone — a source to
  Newton. The schedule lives in the accept hook, where a change of the input
  is a change (an iterate that flips and flips back never was one): a change
  of the *accepted* input creates a transition with the times the operator
  holds at that point (LRM: "at this point it uses the value of td, rise_time,
  fall_time"); with `td = 0` it starts now, from the current output to the new
  value over `rise` (rising) or `fall` (falling), the leading corner entered at
  the head of the breakpoint table and the trailing one set with `CKTsetBreak`
  ("the simulator … place[s] time points at both corners"); with `td > 0` it
  is queued for `t + td` with a breakpoint there, cancelling queued
  transitions due at or after it, and any number may be pending. A change
  during an active ramp is the LRM's *readjustment*: the new slope is taken
  from the interrupted ramp's origin when the new destination continues its
  direction and from its destination when it reverses, over the new time, and
  applied from the point of interruption (Figures 4-7 to 4-12). A zero time —
  no directive, or an edge under a picosecond — is the LRM's "negligible, but
  non-zero" ramp, a thousandth of TSTEP with no trailing breakpoint. An input
  that is not piecewise constant (a sine through a bare `transition()`, which
  the LRM allows and warns "can cause the simulator to run slowly") readjusts
  every point and places no breakpoints: with them, every timepoint bred a
  breakpoint `td` later and the transient never finished (found by `evtedge`
  while this was built).
- **`slew`: `V(z) = clamp(V(y), y_last − neg·h, y_last + pos·h)`** with
  `y_last` the output accepted at the previous point — the input itself while
  it moves within the bounds (`∂V(z)/∂V(y) = 1`, exact at every accepted
  point), an exact linear ramp at the bound otherwise. The truncation hook
  keeps the next step from growing past the corner where the ramp meets the
  input, never rejecting a point for it.
- **DC** is the identity `V(z) = V(y)` (LRM: both operators pass `expr` in
  DC), the stamp `absdelay` uses; the first transient evaluation seeds the
  state from the converged operating point. **AC** is unity — with the delay's
  phase for `transition`, exactly as the absdelay stage it replaced stamped it
  (E-588's contract, pinned by `evtedge`) — and **pz** the zero-delay wire,
  with `absdelay`'s one-time caveat when the transition has a delay.

**What is gone.** `lower_rate_limited_track` and its constants (`TRACK_C`,
`TRACK_GAIN_INF`, `HUGE`, E-697's `RATE_INST`), the `EnableIntegration` DC
switch and the ac/noise reactive gating of E-47 and E-588 — none of them has
anything left to act on. E-696's projections of a negative time or a
wrong-signed or zero rate stay in the compiler, in front of the stores; a
zero rate is still no limit (`+inf` times `h` is `+inf`). `` `default_transition ``
supplies the omitted and the explicit-zero times as before (E-47, E-524).

## Verification

| check | result |
|---|---|
| `transition(cmp ? amp : 0, 0, 1u, 1u)`, amp = 1, 5, 0.2, −3, 10 %–90 % time / 0.8 on both edges | 1.00 µs for every swing (was 1, 5, 0.2, 3 µs) |
| the same under `` `default_transition 1u `` with no time arguments, swings 0 → 1, 0.2 → 1, 0 → 5, 1 → 1.1 | 1.00 µs each (was 1, 0.8, 5, 0.1 µs) |
| the hunt's F2 table: trap and gear at a 10 µs step with a 1 µs, 10 µs and 20 µs edge, a 1 µs step with a zero edge, `maxstep=1u` — max, min, the value at 2.5, 2.9 and 5.5 ms | 1.000000, 0, 1.000000, 1.000000, 0 in every row (was 1.00020, −2.0e-4, 0.999811, 0.999814, 1.82e-4 under trap) |
| `transition(cmp, 0, …)`, `transition(cmp, 1m, …)`, `slew(absdelay(cmp, 1m), 1e6)`, `slew(cmp, 1e6)` at a 10 µs step | all exact (was 1.00057 / 0.999811 plateaus) |
| `ic = ddt(1n · transition(cmp, 0, 1u, 1u))` at a 0.1 µs step: the peak, the plateau maximum, the value at 2.5 ms | 1.00000 mA, 0, 0 (was 1 mA, 0.84 mA, −0.57 mA); the same contribution into a 1 kΩ load: 1 V, 0, 0 (was 0.84 V, 0.57 V) |
| the 0 → 2 ramp over 100 µs reversed after 50 µs (Figure 4-7) | 1.0 at the reversal (was 0.5), 0.5 at +25 µs, 0 by +50 µs, 0.01 at 1.0995 ms |
| a sine through `transition(V(a), 0, 1u, 1u)` and `slew` (evtedge, transedge) | completes and follows (the first build looped for ever on breakpoints) |
| E-512's endpoint table (3 ns … 30 µs), the 25× refinement, the settled value, E-697's 1e13 and 1e30 V/s and the 0.1 ps rise | unchanged, 1.0 everywhere |
| E-47's `defaulttransition` (half-cross times, the 0.875 plateau), E-524's explicit zero and bare forms, E-588's ac/noise unity and −180° delay phase, E-671's delayed transition under the fallback op, E-696's named projections | unchanged |
| the E-697 binaries on the suites | transedge 20 of 26 (the four swings, the slew plateau and the interrupted ramp fail), lrmfilters 13 of 14, opargs 16 of 16 |
| workspace tests; full sweep | green apart from the sourcegen drift; 531 of 531 |

## What this does not do

- `time_tol` (the fifth argument) is accepted and unused: the corners are
  breakpoints, which is as resolved as a timepoint gets.
- The change of the input is dated at the accepted point where the simulator
  first sees it, as before; a comparator that flips between timepoints starts
  its ramp at the next timepoint, not at the crossing. `@(cross)` is the way to
  place a timepoint at the crossing.
- The "negligible, but non-zero" time of a zero transition is a thousandth of
  TSTEP — negligible on the print grid and resolvable by whatever the output
  drives. The LRM leaves the value to the simulator.
- A continuous input through `transition` readjusts the ramp at every point
  without breakpoints; the LRM says to use `slew` for such signals.
- `pz` linearises a delayed `transition` as a zero delay and says so once, as
  it does for `absdelay`.
- The interpolated `print` of a transition output between two timepoints is
  linear, as ngspice's is for every vector; the operator's own value is exact
  at every timepoint.
