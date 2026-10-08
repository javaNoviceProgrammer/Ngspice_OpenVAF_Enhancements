# guardmalloc_examples — Enhancement-813

[E-813](../../enhancements_doc/Enhancement-813.md), F22 of the
[2026-10-08 ngspice + OSDI hunt](../../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
E-677 captures the operating point so that a `@(final_step)` after an ac can evaluate at the
bias. The capture copied one double more than the solution vector holds (`CKTmaxEqNum + 1`
against `SMPmatSize + 1`). It ran at every `op` and at the bias point of every ac and noise
analysis of a circuit with an OSDI device. The read went past the block whenever the vector's
length filled its allocation slot exactly, which depends on the parity of the unknown count.

The decks run under macOS Guard Malloc (`/usr/lib/libgmalloc.dylib`), which faults at the
overrunning access, so a regression fails every time. Elsewhere they run plainly and only the
values are checked.

- **[1]** A module with an internal node through op, dc, ac, noise, tran, tf and sens.
- **[2]** A module without one beside built-in R, C and D, and a noisy module in a subcircuit.
- **[3]** One to eight extra built-in nodes, both parities.
- **[4]** E-677 still holds: `@(final_step)` after an ac reads the bias, 0.2 V.

Run: `python3 verify_guardmalloc.py` (11 checks per solver; 7 fail on the E-810 binaries).
