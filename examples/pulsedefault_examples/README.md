# pulsedefault_examples — a voltage source's PULSE with `PW` or `PER` left out (Enhancement-910)

```
python3 verify_pulsedefault.py
```

10 checks, both solvers (6 fail on E-908).

## The need

F2 of the 2026-10-19 correctness campaign. The manual (4.1.1) gives PW and PER a default of TSTOP,
and the current source reads them that way: a PULSE without a period is one pulse. The voltage
source took an omitted PER as TR + TF + PW and an omitted PW as 0:
- `PULSE(0 1 1u 1u 1u 5u)` repeated every 7 µs, with a third rising edge at 15.5 µs.
- `PULSE(0 1 1u 1u 1u)` was a 2 µs triangle wave.

Its breakpoints followed the same rule. Those of an explicit `PER=0`, which E-446 had made one
pulse in the load only, still repeated.

## What changed

The voltage source reads an omitted PW and PER as TSTOP, in `vsrcload.c` and in `vsrcacct.c`, as
`isrcload.c` and `isrcacct.c` do. A written negative PW is still 0, and a written `PER <= 0` is
one pulse.

## The checks

- **[1]** `PULSE(0 1 1u 1u 1u 5u)` is one pulse, and V and I agree at every point.
- **[2]** `PULSE(0 1 1u 1u 1u)` rises and stays at 1, as the I source does.
- **[3]** With PER left out and with `PER=0`, the V source's time points are the I source's
  (E-908: 139 against 100).
- **[4]** Controls: a written period, `PER=0`, a negative PW, and a pulse count of 2.
