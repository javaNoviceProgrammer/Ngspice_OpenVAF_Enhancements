# Enhancement-875: a voltage source landed on a period's start schedules that period's next corner — floor() read the fifth rise as the end of the fourth period, and a step went past the rise's end

**Scope:** found while folding F2 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice: `spicelib/devices/vsrc/vsrcacct.c`, `VSRCaccept`: the PULSE and repeating PWL cases.
Stock ngspice-46 code.

`examples/pulsecorner_examples/` (new). **ngspice only.**

**Suites:**
- [`pulsecorner_examples`](../examples/pulsecorner_examples/): 5 of 5 per solver. On the E-872
  binaries [1] to [4] fail; [5] is a control.
- 60 random pulses and 60 random repeating PWLs into an RC, under trap, `trbdf2` and `sdirk`: no
  corner or knot is missed. On E-872, under trap, corners were missed in 28 and knots in 32 of
  the 60.
- The full sweep: 579 of 579.

## What was wrong

With [Enhancement-874](Enhancement-874.md), `trbdf2` on a Family A network was 21 times less
accurate than trap at the same tolerance. It had stepped over the end of a 26 ps rise (values
rounded):

```
v0 2 0 pulse(-0.7303 0.1685 6.2449e-09 2.5791e-11 5.9761e-11 3.6389e-09 2.2870e-08)
```

`VSRCaccept` schedules a pulse's next corner when a point is accepted, from the time within the
period, t − TD − PER·floor((t − TD)/PER). The step had landed on the fifth rise's start, where
(t − TD)/PER is 3.999999999999843 in floating point. floor gives 3, so the point reads as the
end of the fourth period, 3.6e-21 s before the next pulse. The source asked for a breakpoint
3.6e-21 s ahead, which is under `minbreak` and dropped. The rise's end went unscheduled until the
next accepted point.

Trap's truncation estimate usually rejects a step across the rise, and the corner is scheduled
before a smaller step reaches it. `trbdf2` and `sdirk` accept the step, and the corner is gone.
Trap is not safe either: in 28 of 60 random pulses into an RC, trap on E-872 missed corners.

A repeating PWL (`r=`) does the same arithmetic. It also wrapped only past its last knot, so a
point landed a hair under the last knot found no knot ahead of it. In 32 of 60 random repeating
PWLs with an edge at each repeat's start, trap missed knots.

## The change

- **PULSE:** a time within `minbreak` of the period's end is taken as the start of the next
  period, so the corner it schedules is the rise's end.
- **Repeating PWL:** a time within `minbreak` of the last knot wraps, and the same rule applies to
  the wrapped time.

Every corner and knot of the 120 random decks is now a point, under trap, `trbdf2` and `sdirk`.
Under trap no pulse deck lost accuracy: the median error went from 1.27e-2 to 1.24e-2, and none
rose by more than half. The Family A network under
`trbdf2` is now 9.5e-6 off against the exact solution (trap 3.5e-5), and under `sdirk` 2.2e-7.

## The checks

`pulsecorner_examples`:
- **[1]** The pulse above into an RC: every corner is a point under trap, `trbdf2` and `sdirk`.
- **[2]** 20 random pulses (seeded) under trap: every corner is a point.
- **[3]** A repeating PWL with an edge at each repeat's start: every knot is a point under trap.
- **[4]** 20 random repeating PWLs (seeded) under `trbdf2`: every knot is a point.
- **[5]** (control) The pulse of [1] under trap at `reltol=1e-5` is within 0.1 % of the exact
  RC response at every point.
