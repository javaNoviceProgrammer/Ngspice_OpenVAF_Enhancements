# Enhancement-874: trbdf2 and sdirk keep their accepted history — the interior stages sat in the slot the truncation estimate reads, and an RC took 580 045 points under trbdf2 where trap took 512

**Scope:** F2 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice:
- `spicelib/analysis/dctran.c`: `staged_top`, the slot above the history that the TR-BDF2 and
  SDIRK steps rotate through; the note for a `maxord` a staged method does not use.
- `spicelib/analysis/cktdojob.c`: `maxord` pinned to the staged method's order, 2 or 3.
- `spicelib/analysis/cktsetup.c`, `cktdest.c`: every state vector is freed.
- `frontend/com_checkpoint.c`: `loadstate` allocates a stage slot the checkpoint carries (added
  with [Enhancement-876](Enhancement-876.md)).
- `include/ngspice/cktdefs.h`, `spicelib/devices/cktinit.c`: `CKTmaxOrderAsked`.

`examples/stagedslots_examples/` (new). **ngspice only.**

**Suites:**
- [`stagedslots_examples`](../examples/stagedslots_examples/): 6 of 6 per solver. On the E-872
  binaries [1], [2] and [4] fail; [3] and [5] are controls; [6] fails on the E-875 binaries.
- `integmethod`, `corenum`, `dynorder`, `maxordnote` and `opamp741` pass under both solvers.
- The campaign's Family A, rerun with the `trbdf2`, `sdirk` and `ordfix` settings on its 540
  networks: no timeouts (there were two), and the staged methods take the points trap takes
  (median ratio 1.0; it was 2.7 for `trbdf2`).
- The full sweep: 579 of 579.

## What was wrong

```
* a sine into an RC
v1 in 0 sin(0 1 100k)
r1 in out 1k
c1 out 0 1n
.option method=trbdf2
.control
tran 1u 50u 0 50u
.endc
.end
```

Points to the end of this RC, under both solvers:

| method | reltol 1e-3 | 1e-4 | 1e-5 | 1e-6 |
|---|---|---|---|---|
| trap | 53 | 117 | 246 | 512 |
| trbdf2 | 130 | 5 626 | 57 898 | 580 045 |
| sdirk | 69 | 1 308 | 26 268 | 265 117 |

A second-order method should need about 3.2 times the points per decade of `reltol`, as trap does
(2.1 to 2.2 here). `trbdf2` and `sdirk` needed ten times: the scaling of a first-order method. A
Family A network under `trbdf2 trgamma=0.8` at `reltol=1e-7` took 5 562 161 points where trap
took 412.

A staged step rotates the state history once per stage, so that each stage formula finds its
predecessors in `CKTstates[1..]`. Afterwards it splices the interior stages back out. The splice
put them in `CKTstates[maxord+1]`, and for `sdirk`'s second stage in `CKTstates[maxord]`. The
truncation estimate reads `CKTstates[0 .. order+1]`. At the default `maxord=2` that is
`CKTstates[3]` for `trbdf2`, which held the interior stage, not q(tₙ₋₂). For `sdirk` at order 3 the
estimate reads `CKTstates[4]`; [Enhancement-419](Enhancement-419.md) raised `maxord` to 3 so that the
slot exists, but the two stages then sat in slots 3 and 4. The estimate compared a stage value
with the old points' spacing, so it scaled with the step instead of its cube. `trbdf2` at
`maxord=3` and `sdirk` at `maxord=6` were right: 388 and 121 points at 1e-6.

## The change

The accepted history keeps its depth, `CKTstates[0 .. maxord+1]`. A staged step rotates through
slots above it, one per interior stage (`staged_top`): slot 4 for `trbdf2`, 5 and 6 for `sdirk`. Its
splice leaves the history as it found it. The slots are allocated when first needed, so a method
set by `option` between runs, or a `loadstate`, gets them. `CKTunsetup` and `CKTdestroy` now
free all eight state vectors. They freed up to `maxord+1` of the current options, which leaked the
rest when `maxord` went down between runs.

A staged method has one order, so `maxord` is pinned to it: 2 for `trbdf2`, 3 for `sdirk`. A
`maxord` other than 2 that does not apply draws a note:
`Note: maxord=6 has no effect with method=trbdf2, whose order is 2.` `trbdf2` now runs point for
point as it did at `maxord=3`.

| method | reltol 1e-3 | 1e-4 | 1e-5 | 1e-6 |
|---|---|---|---|---|
| trbdf2 | 38 | 80 | 183 | 388 |
| sdirk | 34 | 60 | 98 | 165 |

Against the exact response, both are within 1.42 times trap's error at every `reltol`, with fewer
points. `sdirk` takes more points than it did at `maxord=6` (165 against 121 at 1e-6), because
[Enhancement-873](Enhancement-873.md) made its order-3 estimate four times larger, as it should
be. At `maxord=6` on E-872 it was 0.77 V off on this 0.85 V sine at `reltol=1e-3`; it is now
0.039 V off, as trap is (0.038 V).

Larger staged steps also exposed a skipped pulse corner, which
[Enhancement-875](Enhancement-875.md) fixes.

## The checks

`stagedslots_examples`, on a sine into an RC at `reltol` 1e-3 to 1e-6:
- **[1]** `trbdf2`: the points grow by less than 3 times per decade, and end below trap's.
- **[2]** `sdirk`: less than 2.5 times per decade, and below trap's.
- **[3]** (control) Both are within 1.5 times trap's error against the exact solution at every
  `reltol`. E-872 passed it by over-resolving.
- **[4]** `maxord` has no effect: `trbdf2` at `maxord=6`, and `sdirk` at 2 and 6, run point for
  point as at the default, and a note says so for 6.
- **[5]** (control) Trap, then `sdirk`, then `trbdf2` in one session, set by `option`, match
  fresh runs.
- **[6]** A `trbdf2` checkpoint (`savestate`) loads in a fresh process and ends where the
  uninterrupted run ends.

**Update (with [E-876](Enhancement-876.md)).** The stage slot is allocated at a staged run's first
step, so a checkpoint taken under `trbdf2` carried a slot that a fresh `loadstate` circuit had not
allocated, and `loadstate` refused it: "checkpoint state layout does not match circuit". E-872
restored the same checkpoint. `loadstate` now allocates such a slot. (`sdirk` checkpoints are
refused before that, because its order of 3 differs from the default `maxord` the restoring
circuit sees: F6 of the campaign.)
