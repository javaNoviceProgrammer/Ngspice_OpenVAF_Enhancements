# jobreset_examples — Enhancement-840

[E-840](../../enhancements_doc/Enhancement-840.md), F3 of the
[2026-10-10 robustness and correctness campaign](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md).

The circuit keeps a pointer to the last job it ran. An interactive analysis command deletes
the previous command's task, and its jobs, before it parses its own card. A card refused
there, such as `sens v(nosuch)`, `ac dec 0 1 1`, `tran 1u` or `tf v(nosuch) v1`, never reached
the job runner, so the pointer was left on freed memory. The next `reset` read it: a
use-after-free, SIGSEGV under macOS Guard Malloc and silent without it.

The decks run under Guard Malloc (`/usr/lib/libgmalloc.dylib`) where it exists, so a
regression fails every time. Elsewhere they run plainly and only what the deck prints is
checked.

- **[1]** After an `op`, each of five refused commands, then `reset`: the deck runs on, and
  the next `op` reads `v(a)` = 1.
- **[2]** The same after a `tran`.
- **[3]** A paused, stepped transient, a refused `sens` and `reset`: the deck runs on and
  keeps `tran1`.
- **[4]** `remcirc` after a refused command, and with a second circuit loaded.
- **[5]** `op`, `op`, `reset` (control).

Run: `python3 verify_jobreset.py` (14 checks per solver).
