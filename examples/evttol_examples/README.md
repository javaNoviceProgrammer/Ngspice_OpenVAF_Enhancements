# evttol_examples — `cross` and `above` land in the box of their tolerances (Enhancement-911)

```
python3 verify_evttol.py
```

8 checks, both solvers (6 fail on E-908).

## The need

LRM 5.10.3.1 (Figure 5-6) puts an event "after the threshold crossing, and while the signal
remains in the box defined by actual crossing and expr_tol and time_tol". With `expr_tol` given,
"both tolerances shall be satisfied".

The compiler warned that every nonzero tolerance was "accepted but not honored". That has been
false since E-759, which lands the step on the crossing. But the landing did not honour the box:
- It aimed at the box's end, and accepted an iterate up to half a width past it (a landing up to
  a whole width).
- `expr_tol` only ever stopped a landing.

As a result:
- A 1 MHz sine with `time_tol` = 10 ns fired 10.7 ns late.
- A slow ramp with `time_tol` = 1 ms and `expr_tol` = 0.2 fired 5.6 ms late.
- The sine with `expr_tol` = 1 mV fired 67 mV past its threshold.

## What changed

- **The box.** Its width in time is `time_tol`. Without one (or with 0.0) it is two thousandths
  of the step, so a request aims a thousandth past the crossing, as E-759 did. With `expr_tol`
  it is no wider than the time the expression takes to move `expr_tol`.
- **The landing.** A request lands in the middle of the box. An iterate outside the box (past its
  end, or more than `expr_tol` beyond the threshold) asks again.
- **The warning.** "Accepted but not honored" is gone. An `expr_tol` written without a `time_tol`
  warns instead, per LRM 5.10.3.1 ("time_tol shall also be specified"); `lrmevents` [23] and [24]
  check it.

## The checks

- **[1]** `time_tol` = 10 ns on a sine: the event within 10 ns.
- **[2]** `time_tol` = 1 ns on a ramp: 0.5 ns after the crossing, the middle of its box.
- **[3]** A slow ramp with `time_tol` = 1 ms and `expr_tol` = 0.2: within 1 ms.
- **[4]** The sine with `time_tol` = 10 ns and `expr_tol` = 1 mV: within 1 mV and 10 ns.
- **[5]** `above()` the same, at both rises.
- **[6]** Control: the default tolerances count all 20 crossings, each within 2e-3 of the step.
- **[7]** The model's nonzero tolerances draw no warning.
