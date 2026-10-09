# libsens_examples — Enhancements 823 to 825

F7–F9 of the
[2026-10-08 ngspice + OSDI hunt](../../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md):
loading from a model library, model cards inside subcircuits, and Verilog-A tasks raised while
`sens` perturbs a parameter.

- **[1] [E-823](../../enhancements_doc/Enhancement-823.md) (F7).** A `pre_osdi` or `osdi` line
  in an included file names its files beside that file, as a nested `.include` does. It
  resolved them against the top deck's directory, so a library shipping `models.lib` and
  `models.osdi` side by side could not load its object.

  Checked from another directory:
  - the object and `-va` forms;
  - a `.lib` section, a nested include, and a path with a space;
  - the plain `osdi` command;
  - the deck's own line, and a name found nowhere.
- **[2] [E-824](../../enhancements_doc/Enhancement-824.md) (F8).** A `.model` inside a
  `.subckt` is copied per instance, and each copy was found by a linear walk of the model
  list. 32 000 wrappers took 7.9 s with a built-in card inside, against 0.13 s at top level.
  The lookup now uses the model hash. The check covers a built-in card, an OSDI card and an
  XSPICE card, and two subcircuits with a card each.
- **[3] [E-825](../../enhancements_doc/Enhancement-825.md) (F9).** A `$fatal` raised while
  `sens` perturbs a parameter aborts the analysis and names the perturbation, in DC and AC.
  `$finish` and `$stop` end it with a Note. All three were ignored before, and `sens`
  reported every sensitivity.

Run: `python3 verify_libsens.py` (18 checks per solver; 13 fail on the E-822 binaries).
