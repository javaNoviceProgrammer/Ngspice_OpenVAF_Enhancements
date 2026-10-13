# Enhancement-876: dynorder leaves trbdf2 and sdirk at their own order — it re-decided the order every step and froze the step at its first size, and runs never ended

**Scope:** F3 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice: `spicelib/analysis/dctran.c`:
- `staged_method`;
- the dynorder order selection and its rejection-rate order drop skip TR-BDF2 and SDIRK;
- a note when `dynorder` is set with them.

With it, `frontend/com_checkpoint.c`: `loadstate` allocates the stage slot a `trbdf2` checkpoint
carries, a regression of [Enhancement-874](Enhancement-874.md) described in its update.

`examples/dynstaged_examples/` (new). **ngspice only.**

**Suites:**
- [`dynstaged_examples`](../examples/dynstaged_examples/): 5 of 5 per solver. On the E-875
  binaries [1] to [4] fail; [5] is a control.
- `dynorder`, `integmethod`, `stagedslots` and `dynstable` pass under both solvers.
- The campaign's Family A: all 48 `trbdf2`/`sdirk` + `dynorder` runs end, at the points the
  same network takes under trap (median ratio 1.0). On E-872, 37 of them hit the 60 s timeout or
  the 2 GB cap.
- The full sweep: 581 of 581.

## What was wrong

```
* a capacitor that never moves
v1 in 0 sin(0 1 100k)
r1 in 0 1k
r2 x 0 1k
c1 x 0 1n
.option method=sdirk dynorder
.control
tran 1u 50u 0 50u
.endc
.end
```

This took 10 002 points where `sdirk` alone takes 16, every step the first step's 5 ns. A sine
into an RC under `trbdf2 dynorder` took 1 391 814 points where `trbdf2` took 130. A 48 ns network
of the campaign, whose first step was 2e-14 s, did not end in 120 s. In the campaign's Families A
and C, 61 runs never ended.

TR-BDF2 sets the order to 2 at the start of every step and SDIRK to 3: each has one order.
`dynorder` ([Enhancement-128](Enhancement-128.md)) re-decides the order after each accepted step.
When a neighbouring order allows a bigger step, it changes the order and, by its own rule, does
not grow the step in the same step (`newdelta = MIN(delta, bestLte)`). The staged method reset the
order at the next step, so the change happened every step and the step never grew.

## The change

The order selection runs for Gear, Adams and trap only. A staged method's step grows by its
truncation estimate as it does without `dynorder`, and the rejection-rate order drop leaves it
alone. With `dynorder` set, the run says so:

```
Note: dynorder has no effect with method=sdirk, whose order is 3.
```

The capacitor takes 16 points, the RC 38 under `trbdf2`, the same as without `dynorder`, and the
48 ns network ends in 208 points.

## The checks

`dynstaged_examples`:
- **[1]** A sine into an RC: `trbdf2` with `dynorder` runs point for point as `trbdf2`. On
  E-875 it takes the same 38 points to another answer (−0.45196 against −0.45258).
- **[2]** A capacitor that never moves: `sdirk` with `dynorder` runs as `sdirk`.
- **[3]** The 48 ns network under `sdirk maxord=4 dynorder` ends within 20 s.
- **[4]** A note says `dynorder` has no effect with `trbdf2` and with `sdirk`.
- **[5]** (control) `dynorder` still takes Gear above order 2 on the RC.
