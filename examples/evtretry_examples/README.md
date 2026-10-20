# evtretry_examples — an event body and a rejected transient attempt (Enhancement-909)

```
python3 verify_evtretry.py
```

17 checks, both solvers (11 fail on E-908).

## The need

F1 of the 2026-10-19 correctness campaign. E-759 runs an event body once per transient attempt
and lands the step on a crossing. When an attempt was rejected after a body had run in it, what
the body did was kept, and the retry ran it again. The rejection could come from another event's
landing request, another instance's, or the truncation error.

Two counters on one sine, one with the default time tolerance and one with `time_tol` = 1 ps,
read 30 and 20 after 20 crossings. The body's `$strobe` printed for both attempts. A timer that
fired in the rejected attempt had its event moved to it.

## What changed

- **The compiler rolls back.** At a retry it puts back every Real and Integer variable and every
  timer's schedule, as they were at the last accepted point.
- **ngspice holds the messages.** An event body's messages wait for the attempt to be accepted,
  and are dropped when it is not.
- **A short landing is chased once.** A landing that fell short of its crossing gets one more
  request.
- **A declined crossing fires again.** A crossing whose request was declined runs again at every
  retry of the attempt that ran it.
- **The count is served only while a transient steps.** Harmonic balance and the other engines
  that evaluate sample times without accepting any get no rollback.
- **The step after a landing keeps a device's bound.** It is no longer floored past a step bound
  a device asked for.

## The checks

- **[1]** The two counters at max steps of 5 and 20 ns, `dir` 0, +1 and −1: both read 20 or 10,
  and a real twin half of that.
- **[2]** A `$strobe` in the body prints once per crossing:
  - 20 lines, numbered in order;
  - each within 3e-3 of the step of its analytic crossing;
  - the `@(final_step)` line once.
- **[3]** A crossing and a timer in one module, on the campaign deck where a landing rejected the
  attempt the timer fired in:
  - every timer line on its schedule;
  - every crossing within 3e-2 of the step;
  - at every accepted point, both counters equal the number of events up to that time.
- **[4]** Under hb, a variable set at the initial step still reads 1 at the final step; a
  tran is the control.

The relaxation oscillator of `idtassert` [4] covers the re-fired declined crossing.
