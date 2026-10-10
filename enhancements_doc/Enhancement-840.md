# Enhancement-840: a refused analysis command no longer leaves the circuit pointing at a freed job — the next `reset` read it

**Scope:** F3 of the
[robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md).

ngspice:
- `spicelib/analysis/cktdelt.c`: `CKTdelTask` clears `CKTcurJob` when it frees the job it names,
  closing a stepped transient's plot first.
- `frontend/runcoms2.c`: `com_remcirc` deletes the tasks before it frees their circuit.

`examples/jobreset_examples/` (new). **ngspice only.**

**Suites:**
- [`jobreset_examples`](../examples/jobreset_examples/): 14 of 14 per solver, under macOS Guard
  Malloc. 13 fail on the E-838 binaries, all with SIGSEGV; the other is a control.
- The full sweep: 549 of 549.

## What was wrong

```spice
v1 a 0 1
r1 a 0 1k
.control
op
sens v(nosuch)
reset
.endc
```

Without Guard Malloc this deck runs, and the use-after-free goes unnoticed. Under macOS Guard
Malloc (`DYLD_INSERT_LIBRARIES=/usr/lib/libgmalloc.dylib`) it faults every time:

```
DCtran_step_quit+24 <- com_remcirc <- com_rset <- doblock <- cp_evloop
```

How it gets there:
1. The circuit keeps `CKTcurJob` pointing at the last job it ran; `CKTdoJob` sets it and
   never clears it.
2. An interactive analysis command (`if_run`) deletes the previous command's task, and with it
   that job, before it parses its own card.
3. A card refused at that point never reaches `CKTdoJob`, so nothing re-points `CKTcurJob`.
4. `reset` calls `DCtran_step_quit`, which reads `ckt->CKTcurJob->JOBtype` from the freed job.

Any refused card does it:
- `sens v(nosuch)`, a node that does not exist;
- `ac dec 0 1 1`, zero points;
- `tran 1u`, no stop time;
- `tf v(nosuch) v1`;
- `noise v(nosuch) …`.

It happens after an `op` or a `tran` alike, and `remcirc` reads the job the same way. The
campaign's deck fuzz found it as `op`, `sens v(1)`, `reset` in a Monte Carlo deck. A `dc` naming
an unknown source did not fault in the same test.

## The change

**`CKTdelTask`:** a task's jobs die with it. If the circuit's `CKTcurJob` is one of them,
`CKTdelTask` first calls `DCtran_step_quit`, which closes a stepped transient's open plot as
`reset` would, and then clears the pointer. Every caller deletes a task of a circuit that
still exists, except one.

**`com_remcirc`:** it freed the circuit (`if_cktfree`) before deleting its tasks. That was
harmless while `CKTdelTask` ignored the circuit, and would have been a use-after-free of its
own now. The two `deleteTask` calls move ahead of `if_cktfree`; `CKTdestroy` uses no task.

## The checks

`jobreset_examples` runs each deck under Guard Malloc where it exists, and plainly elsewhere:
- **[1]** After an `op`, each of the five refused commands, then `reset`: the deck runs on,
  and the next `op` reads `v(a)` = 1.
- **[2]** The same after a `tran`.
- **[3]** `stop after 20`, `tran`, `step 3`, a refused `sens`, `reset`: the deck runs on, and
  `tran1` stays in the plot list.
- **[4]** `remcirc` after a refused command. Two circuits, a refused command on the first,
  `remcirc`: the second circuit is still there.
- **[5]** `op`, `op`, `reset` (control).
