# Enhancement-720: a source's edge fed straight into `transition` is one change of the input, whatever its width — the integrator resolves a PULSE's 1 ns rise with a dozen accepted points, each of them a change, and LRM 4.5.8's reversal rule took the interrupted ramp's destination, which by then was the input's value at the last of those points on the near side of the output: the readjusted ramp ran at 0.68/tf, set by where the timepoints fell and by the delay path, where the comparator form of the same edge gave the LRM's 1/tf

**Scope:** F3 of the
[second correctness campaign of 2026-09-25](../docs/bug_hunts/2026-09-25_openvaf-r-correctness-campaign-2.md).
**ngspice only.** `src/osdi/osdidefs.h` (`OsdiTransitionState`: the reference ramp
`ref_active/ref_rising/ref_v_orig/ref_v_dest` and `corner_pending`;
`OsdiTransitionPending`: `churn`), `src/osdi/osdiaccept.c` (`transition_start`,
`transition_accept_slot`), `src/osdi/osdiload.c` (the seeding).
[`examples/transedge_examples/`](../examples/transedge_examples/) (section 6, 4 checks,
30 per solver). The hunt page.

**Suites:** `transedge` 30 of 30 per solver, both solvers (27 of 30 on the E-719
binaries); `lrmfilters` 26 of 26, `opargs` 16 of 16, `defaulttransition`, `tranopdelay`
11 of 11, `evtedge` 14 of 14, `hiername`, `domainwarn` 28 of 28, `lrmops` 26 of 26,
`lrmfuncs` 229 of 229, `lrmevents` 26 of 26, `constguard` 75 of 75, `limguard` 110 of
110, `valguard` 113 of 113 and `saveguard` 38 of 38 unchanged; no new build warnings;
full sweep, run alone.

## What was wrong

`transition(V(b), 0, 20u, 30u)` on a source that rises at 5 µs and falls at 15 µs,
when the ramp is at 0.5 — a `PULSE` or `pwl` edge of 1 ns, the ordinary way to write a
digital signal in a deck, against a comparator of the same source inside the model
(`V(b) > 0.5 ? 1.0 : 0.0`), the form [E-698](Enhancement-698.md)'s suite pins:

| input | edge | td | slope after the interruption | reaches 0 (µs after) | LRM 4.5.8, Figure 4-7 |
|---|---|---|---|---|---|
| comparator | 1 ns, 1 ps | 0, 10 µs | −3.333e4 V/s | 15.00 | (0 − 1)/30 µs, 15.00 |
| the source itself | 1 ns, 1 ps | 0 | −2.100e4 | 23.85 | the same |
| the source itself | 1 ns, 1 ps | 10 µs | −2.277e4 | 21.99 | the same |
| the source itself | 1 µs | 0 | −1.800e4 | 28.30 | the same |
| the source itself | 1 µs | 10 µs | −1.705e4 | 29.86 | the same |

— at `reltol` 1e-3 and 1e-6 alike. The LRM's rule for an interrupted rising transition
whose new destination is below the value at the interruption is one line: the slope is
`(v3 − v2)/tf3`, the original transition's *destination* over the new fall time, so a
0 → 1 ramp reversed at 0.5 falls at 1/tf and lands 0.5·tf later. The comparator has
it. The source does not, and its slope depends on the edge's width and on whether a
delay is in the way.

The scheduler E-698 put in the accept hook creates or readjusts a transition at
every change of the *accepted* input. A 1 ns `PULSE` edge is not one accepted point:
the step control resolves it with a dozen — the input read 0.99, 0.97, 0.935, 0.90,
0.893, 0.879, 0.851, 0.795, 0.683, 0.459, 0.2295, 0 at successive accepted points
inside the edge — and each is a change, each a readjustment against the ramp the
previous point had made. For a *continuing* direction the rule takes the origin, which
stays the edge's own level (0 for the rise), so an uninterrupted edge lands exactly:
E-698's four swings and the campaign's three-level input were right. For a *reversal*
the rule takes the destination, and by the point that first reads below the output
(0.459) the ramp's destination is the previous point's value, 0.683; the continuations
after it (0.2295, 0) keep that as their origin, and the ramp to 0 runs at
(0 − 0.683)/tf. With a delay the edge's points come due as a burst at `t + td`,
started on other accepted points, and the last value on the near side is another
one: 0.63/tf for the direct form, 0.68/tf behind the delay, 0.60 and 0.57 for a 1 µs
edge. A digital signal's edge width had become part of the operator's slope.

## What changed

**Every change after an edge's first readjusts against the ramp the first found**
(`transition_start`). E-698 already told the two kinds of change apart: a change that
follows a change (`changed_prev`) is a point inside an edge, or an input that is not
piecewise constant, and gets no breakpoints. That flag is now the *churn* of a change
— carried on a queued transition too (`OsdiTransitionPending.churn`) — and a
readjustment takes its reference levels from the ramp that was active when the run's
first change arrived (`ref_active`, `ref_rising`, `ref_v_orig`, `ref_v_dest`, captured
at every change that is not churn) rather than from the ramp the previous point of the
same edge made. The edge's first point reverses against the destination 1, every later
point of the edge against the same 1, and the ramp to 0 runs at (0 − 1)/tf from the
point of interruption. The comparator form changes once and is untouched, as is
E-698's rule chain for a change that arrives after the input has held still. An
input that never holds still — the sine E-698's suite runs through `transition` — has
the ramp its first change found as reference for the whole run: idle, so each point is
a fresh ramp from the output toward the input over the transition time, a first-order
tracker with that time constant, with no breakpoints as before (0.5063 at 2.5 ms in the
suite, 0.5 ± 0.1 asked).

**The edge's ramp gets its corners** (`transition_accept_slot`, step 4). The points
inside an edge place no breakpoints, so the ramp the edge ends in had no trailing
corner (the landing fell on the print grid, 50 ns late at a 0.1 µs step), and behind a
delay the burst's due times had none, so the final value came due between accepted
points and its ramp started where the step control happened to land, 0.19 µs late on
a 1 µs step. At the first accepted point where the input holds still again the active
ramp's destination time gets its breakpoint ("time points at both corners"), and so
does the due time of the last queued transition when it was queued from an edge — one
breakpoint each per edge, none for an input that never holds still, which is what
E-698's churn rule was for.

## Verification

`transedge` section 6: a 1 ns `PULSE` edge through `transition(V(a), 0, 100u, 100u)`
reversed at 0.5 falls at (0 − 1)/tf as the comparator does — 0.25 at +25 µs, 0 by
+50 µs, y = 0.01 at 1.099 ms (1.120 ms on the E-719 binaries, where +25 µs read 0.325);
the same behind a 10 µs delay, 0.25 at 1.085 ms and 0.01 at 1.109 ms (1.130 ms
before); a 1 ps edge under `reltol=1e-6` — other timepoints inside the edge — the same
slope; an uninterrupted source edge half way at 0.5 µs and done at 1 µs on both edges,
as before. The 26 checks of E-512, E-697 and E-698 unchanged, the Figure 4-7 comparator
check among them.

By hand: the table above rerun — the source's 1 ns and 1 ps edges at −3.333e4 V/s
landing 15.00 µs after, with and without the delay, at `reltol` 1e-3 and 1e-6; the
accepted points inside the edge and the reference each readjustment took; the fifteen
suites; the sweep.

## What this does not do

- A genuinely slow input edge (1 µs against a 20 µs rise, the 1 µs rows above) is
  still the LRM's "unsatisfactory" regime: the readjustment begins at the edge's
  first accepted point, with the output where it is then, and runs at the LRM's slope
  from there — 15.2 µs after the edge's start, where the comparator flips at the edge's
  midpoint and lands 15.55 µs after it.
- Two edges on consecutive accepted points — a glitch one timepoint wide — are one
  run: the second readjusts against the ramp the first found. The regime E-698 already
  treats as churn, without breakpoints.
- A continuous input keeps E-698's contract: it runs, follows, and breeds no
  breakpoints. Which tracker it gets is not specified by the LRM and is not pinned
  beyond the suite's ±0.1.
- `slew` is untouched: it has no readjustment rule.
