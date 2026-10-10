# rebinfinal_examples — Enhancements 826 to 828

F10–F12 of the
[2026-10-08 ngspice + OSDI hunt](../../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md):
`alter` of a binned instance's size, the message of a failed Verilog-A compile, and
`@(final_step)` under `pss` and `hb`.

- **[1] [E-826](../../enhancements_doc/Enhancement-826.md) (F10).** `alter n1 l=5u` moves an
  instance to the bin that covers the new size and says so. It left an OSDI instance on its
  old bin in silence: ngspice re-binned only m-devices.
  - A size no bin covers is refused, with the bins named, where it used to be applied.
  - The same holds for built-in BSIM4 bins.
  - A model that is not binned is the control.
- **[2] [E-827](../../enhancements_doc/Enhancement-827.md) (F11).** A failed compile says
  whether the compiler could not be run (no such file, not on PATH, not executable), with the
  advice on where to put it. A compiler that ran and refused the source gets its exit code
  and a pointer to its own messages. Every failure used to get the advice. `pre_snp` gets the
  same report, where it used to print the raw wait status.
- **[3] [E-828](../../enhancements_doc/Enhancement-828.md) (F12).** `pss` and `hb` fire
  `@(final_step)` once, at the end of the period, on the steady state. They never fired it.
  `tran` and `qpss` are the controls.

Run: `python3 verify_rebinfinal.py` (15 checks per solver; 11 fail on the E-825 binaries).
