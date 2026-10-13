# Enhancement-877: a PULSE current source schedules its corners as a voltage source does — it waited to land on each corner before asking for the next, and a rise shorter than minbreak ended the chain

**Scope:** F4 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice:
- `spicelib/devices/isrc/isrcacct.c`, `ISRCaccept`: the PULSE case schedules the next corner from
  the time within the period, as `VSRCaccept` does.
- `isrcdefs.h`: `ISRCbreak_time`.
- `isrctemp.c`: it is re-armed per run.

Stock ngspice-46 code. `examples/isrcpulse_examples/` (new). **ngspice only.**

**Suites:**
- [`isrcpulse_examples`](../examples/isrcpulse_examples/): 5 of 5 per solver. On the E-875
  binaries [1] and [2] fail; [3] to [5] are controls.
- `pulsecorner`, `prbs` and `dynstable` pass under both solvers.
- The campaign's Family A: on the 68 networks with a current pulse whose edge is under
  `minbreak`, the median error of plain trap at default tolerance goes from 5.3e-4 to 1.8e-4, the
  level of the other networks. 13 are better and none is worse.
- The full sweep: 581 of 581.

## What was wrong

```
* the same pulse as a current and as a voltage source
i1 0 b pulse(0 1m 0.7u 0.1p 0.1p 1.4u 3u)
r1 b 0 1k
c1 b 0 1n
.control
tran 0.1u 13u
.endc
.end
```

Against the exact response this was 3.0e-2 off, in 219 points. The same pulse from a voltage
source through 1 kΩ into the same capacitor has the same ODE, and was 2.8e-4 off in 381 points.

The voltage source schedules a pulse's next corner from the time within the period and its own
next-corner time (`VSRCbreak_time`), and skips a corner closer than `minbreak`. The current source
had the older chain. A corner scheduled the next only when an accepted point landed on it, to
1e-7 of the pulse width (`SAMETIME`). A rise of 0.1 ps is shorter than `minbreak` (5 ps here) and
cannot be landed on, so the chain stopped. From the second fall on, the nearest point to each edge
was 17.4 ns after it. In the campaign's Family D, the same chain was behind three of the five
resumed runs that were more than 10× less accurate than an uninterrupted run, and two of the four
checkpoint continuations: the pause moved the run's points off a corner. They are now within
2.6 times the uninterrupted run (seeds 8, 124, 304) and equal to it (69, 321); they were 34 to
4 666 times worse.

## The change

The PULSE case of `ISRCaccept` is `VSRCaccept`'s:
- `ISRCbreak_time` holds the next corner;
- each accepted point at or past it schedules the corner after it, skipping one closer than
  `minbreak`;
- a point within `minbreak` of the period's end counts as the next period's start
  ([Enhancement-875](Enhancement-875.md));
- a pulse count (the 8th parameter) and a `phase` under `ngbehavior=xs` are handled as there.

The defaults are those of `ISRCload` ([Enhancement-446](Enhancement-446.md)), so the corners are
the waveform's:
- a rise or fall that is not positive takes `tstep`;
- a negative width runs to `tstop`;
- a period that is missing or not positive does not repeat.

`ISRCtemp` re-arms the break time for each analysis, as `VSRCtemp` does
([Enhancement-498](Enhancement-498.md)).

The current source now puts its points where the voltage source puts them. On 15 random pulses
with edges from 1e-8 to 1e-2 of the period the two grids agree to 3e-15. The pulse above is
2.8e-4 off in 381 points, as from the voltage source.

## The checks

`isrcpulse_examples`:
- **[1]** The pulse above: the current source is within 1.2 times the voltage source's error, in
  as many points.
- **[2]** 15 random pulses (seeded): the current and the voltage source put their points at the
  same times.
- **[3]** (control) A pulse with a count of 2: the same grid as the voltage source.
- **[4]** (control) A second `tran` in the same session repeats the first, point for point.
- **[5]** (control) With 1 ns edges both sources land on every corner.
