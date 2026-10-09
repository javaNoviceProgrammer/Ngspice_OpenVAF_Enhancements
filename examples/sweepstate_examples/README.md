# sweepstate_examples — Enhancements 820 to 822

F4–F6 of the
[2026-10-08 ngspice + OSDI hunt](../../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md):
what a `.dc` sweep of a temperature or an OSDI parameter does to a Verilog-A model's state,
its final step, the values it leaves behind, and the place its messages name.

- **[1] [E-820](../../enhancements_doc/Enhancement-820.md) (F4).** `dc temp`, `dc @n1[p]` and
  `dc @tm[q]` re-fire `@(initial_step)` at each point, which BSIM4-style models need (LRM
  5.2.1).
  - The variables now carry from point to point (LRM 4.6.2). A counter read the same at every
    point before.
  - `@(final_step)` sees the last point, not the restored temperature or parameter.

  Also checked: a source sweep, a nested source and temperature sweep, an op after the sweep
  (its variables start again), and `$finish` mid-sweep.
- **[2] [E-821](../../enhancements_doc/Enhancement-821.md) (F5).** A sweep stopped by `$fatal`
  puts the swept source or parameter back. The next op runs on the netlist's value instead of
  raising the same `$fatal`. A `$stop` still keeps its value for `resume`.
- **[3] [E-822](../../enhancements_doc/Enhancement-822.md) (F6).** A message raised in a setup
  pass is labelled with the sweep point being applied, or with "(during setup)" outside a
  sweep. It used to name the previous point, or whatever analysis ran last. A setup `$fatal`
  prints once.

Run: `python3 verify_sweepstate.py` (18 checks per solver; 14 fail on the E-819 binaries).
