# Enhancement-909: what an event body did in a rejected transient attempt is undone — a `@(cross)` beside a second event read 30 crossings for 20 and printed its `$strobe` twice; the retry now starts from the accepted point's variables and timer schedules, the body's messages wait for the attempt to be accepted, a short landing is chased once, and the step after a landing keeps a device's bound

**Scope:** F1 of the
[sources, code models, operators and statistics correctness campaign of 2026-10-19](../docs/bug_hunts/2026-10-19_ngspice-openvaf-r-sources-models-statistics-correctness-campaign.md).
Both trees.

Compiler:
- `hir_lower/src/state.rs`: `rollback_at_retry`, and `insert_var_init` reads the rolled-back value.
- `hir_lower/src/lib.rs`: `HirInterner::rollback_event_slots`.
- `hir_lower/src/stmt.rs`:
  - `lower_timer` registers its schedule slot.
  - `event_landing_context` chases a short landing once, and re-runs a declined firing at a retry.
  - `event_landing_record` tells a short refinement from a short landing.

ngspice:
- `osdi/osdicallbacks.c`: event-body messages are held per attempt.
- `osdi/osdiload.c`, `osdi/osdidefs.h`: an evaluation at a new time opens an attempt.
- `osdi/osdiaccept.c`: the accepted-point count is served only while the circuit steps in
  MODETRAN since an accept.
- `osdi/osditrunc.c`: records the smallest step bound a device asked for.
- `spicelib/analysis/dctran.c`: the step after a landing is not floored past that bound.
- `include/ngspice/cktdefs.h`: `CKTmodelBound`.

**Suites:**
- [`evtretry_examples`](../examples/evtretry_examples/) (new): 17 checks per solver, 11 of
  which fail on E-908.
- `rebinfinal` [3] (hb), which caught an interim build.
- The event suites, unchanged: `evtedge`, `simctrl`, `idtassert`, `discontinuity`, `finalstep`,
  `lrmevents`, `eventcond`, `opargs`, `varinit`, `multianalog`, `intstate`, `analoginit`,
  `deckdomain`, `hiername`, `lrmcorner`, `lrmkernel`, `domainrt`, `defaulttransition`, `evtnoise`,
  `rtdomain`, `cardbound`, `sweepbounds`, `hunt13slips`, `constfold`.
- The full sweep: 598 of 598.

## What was wrong

```verilog
module cnt(in, out);
  inout in, out; electrical in, out;
  parameter real thr = 0.3;
  parameter integer dir = 0;
  integer n;
  analog begin
    @(initial_step) n = 0;
    @(cross(V(in) - thr, dir)) n = n + 1;
    V(out) <+ n;
  end
endmodule
```

Two of these on one `sin(0 1 1meg)` for 10 µs, one as written and one with `time_tol` = 1 ps,
should both read 20 (`dir` = 0) or 10:

| `dir` | max step | as written | with `time_tol` |
|---|---|---|---|
| 0 | 5 ns | **30** | 20 |
| 0 | 20 ns | **27** | 20 |
| +1 | 5 ns | **17** | 10 |
| +1 | 20 ns | **11** | 10 |
| −1 | 5, 20 ns | 10 | 10 |

E-759 runs an event body once per transient attempt, on the attempt's first iterate, and lands the
step on the crossing by rejecting an attempt that overshot it. Its own requests were handled, but
an attempt can be rejected for other reasons after a body ran in it:
- another event asked for a landing,
- another instance did (the second counter's margin is smaller, so it asks for steps the first
  has already fired in),
- the truncation error failed.

The variables a body changed are stored at the end of every evaluation (E-7), so the rejected
attempt's `n = n + 1` survived. The retry reached the same crossing, compared against the last
accepted sample as E-759 has it do, and ran the body again. A `$strobe` in the body printed for
both attempts, the second time with an earlier `$abstime`: an event-body message is
`LOG_FLAG_IMMEDIATE`, so nothing held it.

A timer was hit the other way. Its next event time is stored state too. When the attempt it fired
in was rejected and the retry was cut short of the event, the schedule had already moved on, so
the event belonged to a point that never existed. The counter counted it from the retry, which is
before the event time.

Fixing that showed two older faults:
- **A short landing was not chased.** E-759 lands on a straight-line estimate of the crossing
  plus a margin. On a curved signal that can fall 1.4 ns short of the crossing at a 5 µs step.
  The next attempt made no request (E-759: "a landing that fell short ... is not chased"), and the
  crossing fired where that attempt ended, up to a step late. Over 40 random decks of the
  campaign's family C, the worst crossing of a `cross(x, 0)` deck was a median 0.997 of the step
  from the analytic crossing.
- **The step after a landing ignored a device's bound.** dctran floors that step at an eighth of
  the landing step. The floor was meant for the truncation estimate, but it also overrode a timer's
  step bound. A timer due 0.45 µs after a crossing at a 5 µs step was stepped over, 5e-3 of its
  period late. Before this fix the timer had fired in the rejected attempt instead, so the
  problem did not show.

## What changed

**The compiler rolls back.** It uses the attempt structure of E-759 for the module as a whole:
- **A new point.** `$osdi$point` moved since the last evaluation, so the previous evaluation
  belonged to the accepted attempt. Each persistent value it stored is copied aside.
- **A retry.** The time moved and the count did not. The retry starts from those copies.

Persistent values are every Real and Integer variable a later evaluation reads (array elements are
variables), and every timer's next event time. Between the iterates of one attempt nothing changes.
Outside a transient past t = 0, and on a simulator that does not serve the count, the stored values
are read as before, so a dc sweep still carries its variables (E-820). The cost per persistent
value is one more instance slot and two selects.

**Two E-759 rules are adjusted.**
- *A landing that fell short is chased once.* The next attempt may ask again, as a refinement
  whose landing asks nothing. A refinement that falls short as well is not chased, which keeps
  E-759's guard against approaching a crossing for ever.
- *A declined request is fired again at a retry.* A crossing whose request ngspice declined (the
  landing would sit under E-504's step floor) is fired at the next point's first iterate. When
  that attempt is rejected, the rollback restores the variables, so the retry fires it again.
  `idtassert` [4] caught this: without it, the relaxation oscillator's reset was undone and never
  re-armed, and it stayed in reset.

**ngspice holds the messages.** In a transient past t = 0, a `LOG_FLAG_IMMEDIATE` message (an
event body's `$strobe`, `$display`, `$warning`, ...) is held for its attempt:
- it prints when OSDIaccept flushes, ahead of the converged iteration's deferred output (the
  order it always had);
- it is dropped when an evaluation at a new time starts before an accept.

An operating point, a sweep, a final step and the `analog initial` block print at once as before,
and so do `$debug` and `$fatal`.

**The count is served only while a transient steps.** E-759 served `$osdi$point` in every
analysis, but harmonic balance, the envelope and the shooting engines evaluate MODETRAN sample
times without accepting any. A model reads "the time moved and the count did not" as a retry, so
an interim build rolled `@(initial_step)`'s counter back at every sample: `rebinfinal` [3]'s hb
final step read 0 for 1. The count is now served (`OSDIpointSeq`) from an accept until the next
evaluation outside MODETRAN. DCtran, DCpss and optran accept their t = 0 point before they step,
so they are unchanged. HB-style analyses get E-587's evaluation-to-evaluation rules for
`cross`/`above` and no rollback, as they had before E-759 for the events.

**dctran keeps a device's bound.** OSDItrunc records the smallest positive bound a device asked
for (`$bound_step`, a timer). The step after a landing is floored at an eighth of the landing step
as before, then capped at that bound.

## Measured

The table above, on this build: 20, 20, 10, 10 and 10, and the same with `time_tol`. A
`$strobe("XC %d", n)` in the body prints 20 and 10 lines, numbered in order; E-908 printed 30
and 17.

The campaign's family C, 40 decks of `cross` and `timer` on a sine:

| | E-908 | this build |
|---|---|---|
| decks with a wrong crossing count | 8 | 0 |
| decks with a wrong timer count | 0 | 0 |
| worst crossing per deck, `dir` = 0, median (of the step) | 1.0 | 1.6e-3 |
| ... `dir` = +1 | 1.1e-3 | 1.0e-3 |
| ... `dir` = −1 | 1.9e-3 | 9.9e-4 |
| worst crossing of all decks | a full step | 2.2e-2 |
| worst timer event (of the period) | 2.0e-7 | 2.0e-7 |

In the three decks above 3e-3 a refinement fell under E-504's step floor (the span over 10⁶, 8e-3
of the step in these decks). It was declined, and the crossing fired at the next point.

## The checks

`evtretry_examples` (new), under both solvers:
- **[1]** The two counters at 5 ns and 20 ns, `dir` 0, +1 and −1: both read 20 or 10, and a real
  twin (`s = s + 0.5`) half of that. E-908 read 30, 27, 17 and 11.
- **[2]** A `$strobe` in the body:
  - prints 20 lines, numbered 1 to 20, in time order (E-908: 30);
  - each line is within 3e-3 of the step of its analytic crossing;
  - the `@(final_step)` line prints once, with 20.
- **[3]** The campaign's deck where a landing rejected the attempt a timer fired in:
  - 82 timer lines within 1e-9 of tstart + k·tper;
  - 20 crossings within 3e-2 of the step;
  - at every one of the 626 accepted points, both counters equal the number of events up to that
    time. E-908 had 3 timer points and 428 crossing points wrong.
- **[4]** Under hb, a variable set by `@(initial_step)` still reads 1 at the final step; a tran
  is the control.

## Limits

- **A file written from an event body.** Such a write is immediate in the compiled runtime and
  is not held: a rejected attempt's line stays in the file.
- **String variables.** These are not rolled back.
- **A short refinement.** It fires where the next attempt ends, as E-759 did for every short
  landing.
- **E-504's step floor.** It bounds how close a landing can come: a request below it is declined
  and the crossing fires at the next point.
