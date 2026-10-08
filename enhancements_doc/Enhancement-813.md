# Enhancement-813: OSDIload's bias-point capture reads within the solution vector — it copied one double past its end at every `op`

**Scope:** F22 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `osdi/osdiload.c`: new `osdi_solution_len` (`SMPmatSize + 1`), used by
  `osdi_op_solve_capture` and by `OSDIfinalStep`'s check of the capture.

`examples/guardmalloc_examples/` (new, eleven checks per solver). **ngspice only.**

**Suites:** [`guardmalloc_examples`](../examples/guardmalloc_examples/) 11 of 11 per solver under
Guard Malloc (7 fail on the E-810 binaries, each with SIGSEGV); the full sweep, 539 of 539.

## What was wrong

E-677 captures the operating point, so that a `@(final_step)` after a small-signal analysis
evaluates at the bias rather than at the small-signal solution. It takes the capture at the
`MODEINITSMSIG` load. `DCop` issues that load at the end of every `op`, not only before an ac,
so the capture runs at every `op` and at the bias point of every ac and noise analysis of a
circuit with an OSDI device.

The capture copied `CKTmaxEqNum + 1` doubles out of `CKTrhsOld`. `NIreinit` allocates
`CKTrhsOld` and its siblings with `SMPmatSize + 1` doubles, and that is `CKTmaxEqNum`, the next
equation number. So it read one double past the end, every time. The value landed in the
snapshot and was never used, so no result was wrong.

The read was invisible whenever the vector's byte length left padding in its allocation slot. It
went past the block whenever the length filled the slot exactly, which depends only on the
parity of the circuit's unknown count. Under macOS Guard Malloc that is `EXC_BAD_ACCESS` in
`_platform_memmove <- OSDIload <- CKTload <- DCop`; outside it, a read that crosses into an
unmapped page would crash. The hunt met it first with an OSDI internal node, then while
verifying the D slips with no internal node beside built-in R, C and D. A one-device sweep
(below) faults at 2, 4, 6 and 8 extra nodes and not at 1, 3, 5 or 7.

E-689's `uic` code in the same file already used `SMPmatSize(ckt->CKTmatrix) + 1`. The
checkpoint code had met the same trap (`com_checkpoint.c`).

## The change

`osdi_solution_len(ckt)` is `SMPmatSize(CKTmatrix) + 1`, the vector's real length (0 with no
matrix). The capture copies that many doubles. `OSDIfinalStep`'s check that the capture covers
the circuit compares against the same length.

## The checks

`guardmalloc_examples`, under Guard Malloc where it exists (macOS); elsewhere the same decks run
plainly and only the values are checked:

- **[1]** A module with an internal node, through op, dc, ac, noise, tran, tf and sens: each
  clean, with the right answer (`v(n1#mid)` = 0.5, the ac magnitude, the noise spectrum, the
  transfer function, the sensitivities).
- **[2]** The decks that faulted while the D slips were verified: a module without an internal
  node beside built-in R, C and D (op and dc), and a noisy module inside a subcircuit (its
  contribution 2.04e-9).
- **[3]** One to eight extra built-in nodes beside the module, both parities: every op clean.
- **[4]** E-677 still holds: `@(final_step)` after an ac reads the bias, V = 0.2, not the ac
  solution, 1.

On the E-810 binaries 7 of the 11 fail with SIGSEGV: op, ac, noise, both [2] decks, the even
lengths of [3], and [4]. dc, tran, tf and sens pass there, because they issue no
`MODEINITSMSIG` load.

## Limits

- The suite's Guard Malloc runs are macOS-only (`/usr/lib/libgmalloc.dylib`). On Linux and
  Windows it checks values only; this over-read had no visible effect on values.
