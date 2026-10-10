# Enhancement-842: `envelope` checks that its settling transient reached its end — after a device refused at setup it copied from a NULL solution vector

**Scope:** F5 of the
[robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md).

ngspice: `frontend/com_envelope.c` (the check after the settling transient).
`examples/jobreset_examples/` (section [7]). **ngspice only.**

**Suites:**
- [`jobreset_examples`](../examples/jobreset_examples/): 21 of 21 per solver. The refusal check
  in [7] fails on the E-840 binaries with SIGSEGV; the other check in [7] is a control.
- [`sensstate_examples`](../examples/sensstate_examples/): 17 of 17. Its `envelope` over a
  resistor divider caught the first cut of this check (below).
- The full sweep: 549 of 549.

## What was wrong

```spice
v1 1 0 dc 1 sin(0 1 1meg)
r1 1 2 1k
c1 2 0 1n
t1 2 0 3 0 z0=0 td=1n
r2 3 0 50
.control
envelope 2 1meg 10u
.endc
```

`TRAsetup` refuses the line (`z0 = 0 is not a usable characteristic impedance`), so the
settling transient never runs. `envelope` carried on, and crashed every time, with or without
Guard Malloc:

```
_platform_memmove (address 0x0) <- EFanalysis+332 <- com_envelope <- doblock
```

Enhancement-502 had added a check after the settling transient for exactly this. But it asked
only whether `CKTmatrix` existed, and the matrix is created when the circuit is, before any
device setup. A refusal in a device's `DEVsetup` stops `CKTsetup` before `NIreinit` allocates
`CKTrhsOld` and the state vectors. So the check passed and `EFanalysis` did
`memcpy(x, ckt->CKTrhsOld, …)` from NULL.

The campaign's deck fuzz found it: the line `tran 0 0`, inserted into `envelope_demo.cir`, reads
as a lossless line named `tran`. The same refusal followed by 27 other commands was refused
cleanly; `envelope` was the only command that read the state of its own internal run.

## The change

The check now asks for what `EFanalysis` uses:
- the solution vector (`CKTrhsOld`);
- the state vectors, when the circuit has states (`CKTnumStates > 0`);
- a transient that reached `Tsettle`. `CKTdoJob` starts every job at `CKTtime` = 0, so a
  setup refusal and a transient that gave up part-way both stop short of it.

A circuit with no charges has no state vector at all. The first cut asked for one
unconditionally and refused `envelope` over a resistor divider; the full sweep caught it in
`sensstate_examples`.

```
Error: envelope: the settling transient did not run, so there is no state to follow (check the
deck's operating point and time step).
Error: envelope: the settling transient stopped at t = … s of … s, so there is no settled state
to follow (check the deck's time step).
```

## The checks

`jobreset_examples` [7]: `envelope` after the z0 = 0 line is refused with the first message,
and the deck runs on, under Guard Malloc too. The control runs `envelope` over a divider with
no charges: `out_amp` = 0.5. `envelope_examples` (five checks of a working
envelope) and `nanguard_examples` (E-502's refusals) pass unchanged.
