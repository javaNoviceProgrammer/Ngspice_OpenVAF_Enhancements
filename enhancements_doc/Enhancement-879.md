# Enhancement-879: loadstate restores a checkpoint taken with any maxord, and a mismatch names the order — every checkpoint above maxord=2 was refused as "does not match this circuit (equations 4 vs 4, states 2 vs 2)"

**Scope:** F6 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice: `frontend/com_checkpoint.c`, `loadstate`:
- the integration method and `maxord` are copied from the task before the circuit is set up,
  with [Enhancement-874](Enhancement-874.md)'s pin for the staged methods;
- the mismatch message names the maximum order.

`examples/ckorder_examples/` (new). **ngspice only.**

**Suites:**
- [`ckorder_examples`](../examples/ckorder_examples/): 5 of 5 per solver. On the E-875 binaries
  [1] to [4] fail; [5] is a control.
- `checkpoint` (22 of 22) and `stagedslots` pass.
- The full sweep: 583 of 583.

## What was wrong

```
* run part of a transient and save it; then, in a fresh process, load it
v1 a 0 pulse(0 1 0 1n 1n 1u 2u)
r1 a b 1k
c1 b 0 1n
.option sparse method=gear maxord=3
.tran 10n 4u
.control
stop when time > 1.5u
run
savestate ck.bin              ; the second deck has `loadstate ck.bin` here
.endc
.end
```

```
Error: loadstate: checkpoint does not match this circuit (equations 4 vs 4, states 2 vs 2).
```

The same happened with `maxord=3` alone, `method=adams maxord=4`, `gear maxord=6 dynorder`,
`method=trbdf2 maxord=3`, and `method=sdirk`, whose order is 3. Only `maxord=2` restored. In the
campaign's Family D, 34 of 96 checkpoint trials stopped here.

`loadstate` sets the circuit up itself when it is not set up yet, as it is in a fresh process.
`CKTdoJob` copies the task's options into the circuit only when the analysis is dispatched, at the
resume, after that setup. [Enhancement-180](Enhancement-180.md) copied the KLU flags across that
gap. The integration options were not copied, so the circuit had the default `maxord` of 2. The
signature check compares the saved `maxord` with it, and the message printed the two counts that
matched, not the order that did not.

## The change

Before the setup, `loadstate` copies the method and `maxord` from the task. A staged method's order
is pinned as `CKTdoJob` pins it: 2 for `trbdf2`, 3 for `sdirk`. The checkpoint then meets the
circuit it was taken from. A real mismatch names the order:

```
Error: loadstate: checkpoint does not match this circuit (equations 6 vs 6, states 4 vs 4, maximum order 3 vs 2).
```

Every setting above now restores, and the continuation ends where the uninterrupted run does.
It does not follow the uninterrupted run's time grid (F7 of the campaign), so the two agree to
about 3e-8, not to the bit.

## The checks

`ckorder_examples`, every deck under `.option sparse` (checkpoints need it:
[Enhancement-131](Enhancement-131.md)):
- **[1]** `gear maxord=3`: the checkpoint restores in a fresh process, and v(b) at 2.5 µs is the
  uninterrupted run's to 1e-6.
- **[2]** `adams maxord=4`, and `gear maxord=6` with `dynorder`: the same.
- **[3]** `sdirk`: the same.
- **[4]** A checkpoint taken at `maxord=3` and loaded into a deck at `maxord=2` is refused with
  "maximum order 3 vs 2" in the message.
- **[5]** (control) `maxord=2` restores, as before.
