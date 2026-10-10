# limfinal_examples — Enhancements 829 to 831

F13–F15 of the
[2026-10-08 ngspice + OSDI hunt](../../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md):
a Verilog-A `$fatal` inside `@(final_step)`, E-543's BJT limiting on a module that is not a
transistor, and `.option saveused` with an `@dev[param]` in a `.meas` card.

- **[1] [E-829](../../enhancements_doc/Enhancement-829.md) (F13).** A `$fatal` in
  `@(final_step)` now fails the run in `op`, `tran`, `dc` and `hb`: an error line and exit
  status 1. The analysis's results stay readable. It used to print and nothing more, exit
  status 0. A `$finish` or `$stop` there gets a Note; they were silent. A `$fatal` in
  `@(initial_step)` is the control.
- **[2] [E-830](../../enhancements_doc/Enhancement-830.md) (F14).** A linear `c,b,e` resistor
  network is no longer given the BJT junction limiting. It took 577 iterations and gmin
  stepping for an operating point that needs 3. Only a module with a polarity parameter
  `type` is limited now; the same network with `type` is the control.
- **[3] [E-831](../../enhancements_doc/Enhancement-831.md) (F15).** `.option saveused` beside a
  block with no output command now saves the `@dev[param]` vectors the deck's `.meas` cards
  read. They were lost ("holds 1 point(s)"). The controls are a block with an output command
  and the same deck without the option.

Run: `python3 verify_limfinal.py` (14 checks per solver; 10 fail on the E-828 binaries).
