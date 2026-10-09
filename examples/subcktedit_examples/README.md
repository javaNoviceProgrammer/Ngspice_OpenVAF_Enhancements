# subcktedit_examples — Enhancements 817 to 819

F1–F3 of the
[2026-10-08 ngspice + OSDI hunt](../../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md):
editing and naming things inside subcircuits.

- **[1] [E-817](../../enhancements_doc/Enhancement-817.md) (F1).** `alterparam cell rr=100` on a
  parameter of the `.subckt` line:
  - an instance that gave `rr` on its own line keeps it;
  - the default moves, for the instances that took it;
  - a Note names who kept their own value.

  It overrode every instance before: 4 mA became 30 mA. The documented inner-`.param` form
  still changes everywhere. Also checked: a nested call, and an OSDI card reading the
  parameter.
- **[2] [E-818](../../enhancements_doc/Enhancement-818.md) (F2).** `altermod gm` with `gm`
  only inside a subcircuit no longer claims that a top-level card was changed. The note says
  that none exists, that nothing changed, and names a copy. With a real top-level card the
  note is unchanged.
- **[3] [E-819](../../enhancements_doc/Enhancement-819.md) (F3).** The `x1.n1` spelling of a
  device inside a subcircuit, flattened to `n.x1.n1`, now works in:
  - `.ic` and `.nodeset` on an internal node, including a Verilog-A child's
    `x1.n1#c1.mid`;
  - `.save` of an operating-point variable;
  - an analysis command typed before the first setup (`tf v(x1.n1#mid) v1`).

  A built-in BJT's internal node is accepted as well. A name that is no device under either
  spelling is still refused.

Run: `python3 verify_subcktedit.py` (16 checks per solver; 13 fail on the E-816 binaries).
