# Enhancement-910: a voltage source's PULSE with `PER` left out is one pulse — it repeated every TR + TF + PW, and with `PW` left out too it was a triangle wave, where the manual gives both a default of TSTOP and the current source with the same line gave one pulse

**Scope:** F2 of the
[sources, code models, operators and statistics correctness campaign of 2026-10-19](../docs/bug_hunts/2026-10-19_ngspice-openvaf-r-sources-models-statistics-correctness-campaign.md).

ngspice:
- `spicelib/devices/vsrc/vsrcload.c`: an omitted PW or PER is TSTOP.
- `spicelib/devices/vsrc/vsrcacct.c`: the breakpoints use the same rule, and an explicit `PER=0`
  is one pulse there too.

**ngspice only.**

**Suites:**
- [`pulsedefault_examples`](../examples/pulsedefault_examples/) (new): 10 checks per solver, 6 of
  which fail on E-908.
- `argdiscard` and `isrcpulse`, unchanged.
- The full sweep: 598 of 598.

## What was wrong

```
V1 a 0 PULSE(0 1 1u 1u 1u 5u)      * PER left out
I1 0 b PULSE(0 1 1u 1u 1u 5u)
```

At 20 µs `v(a)` was 1 and `v(b)` 0. The voltage source repeated every TR + TF + PW = 7 µs, with a
third rising edge at 15.5 µs, while the current source gave one pulse. With `PW` left out as well,
`PULSE(0 1 1u 1u 1u)`, the voltage source was a 2 µs triangle wave: 0 at 5 µs, 0.5 at 12.5 µs.
The current source rose to 1 and stayed there.

The manual (4.1.1) gives PW and PER a default of TSTOP, and its table of a single pulse is what
the current source does. SPICE3 and LTspice read a PULSE without a period as one pulse too.
`vsrcload.c` took an omitted PW as 0 and an omitted PER as TR + TF + PW, and `isrcload.c` took
both as `CKTfinalTime`.

E-446 made an explicit `PER=0` a single pulse in the load and kept the omitted rule "so no
existing deck changes". It left `vsrcacct.c`, which schedules the source's breakpoints, at
TR + TF + PW for both. So a `PER=0` pulse got the time points of a repeating one: 139 against the
current source's 100 over 40 µs.

In the campaign's run of 1,500 random sources, 74 voltage-source PULSE cases differed from the
manual this way, all with PW or PER left out.

## What changed

The voltage source reads an omitted PW and an omitted PER as TSTOP, in the load and in the
breakpoints, as the current source does. A written negative PW is still 0, and a written
`PER <= 0` is one pulse (E-446), in both files now.

This changes what a deck that leaves the period out does: it gets the single pulse the manual
describes. No suite relied on the old rule: every PULSE in the suites writes its period, and the
two built from format strings (`argdiscard`'s E-446 pair, `isrcpulse`) fill one in.

## The checks

`pulsedefault_examples` (new), under both solvers:
- **[1]** `PULSE(0 1 1u 1u 1u 5u)` is one pulse: 0.5, 1, 0.5, 0, 0 and 0 at 1.5, 4, 7.5, 10, 15.5
  and 30 µs, and the V and I sources agree at every point. E-908: 1 at 10 µs, a repeat.
- **[2]** `PULSE(0 1 1u 1u 1u)` rises and stays at 1 at 5, 12.5 and 30 µs, as the current source
  does. E-908: 0 at 5 µs.
- **[3]** With PER left out and with `PER=0`, the voltage source's time points are the current
  source's. E-908: 139 against 100.
- **[4]** Controls: a written 5 µs period repeats, `PER=0` is one pulse, a negative PW is a
  zero-width pulse, and a count of 2 stops after two pulses.
