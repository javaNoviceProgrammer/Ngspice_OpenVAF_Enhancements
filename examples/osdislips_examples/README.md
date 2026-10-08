# osdislips_examples — Enhancements 796 to 810

The smaller slips D1 to D17 of the
[ngspice + OSDI hunt of 2026-10-08](../../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
Each is pinned end-to-end through ngspice, with openvaf-r compiling the models:

- **[1] [E-796](../../enhancements_doc/Enhancement-796.md) (D1).** `altermod` and `alter` of an
  integer parameter handle it as the card does:
  - a non-integral value is rounded with a warning;
  - -2.5 becomes -3;
  - a value no integer holds is refused.
- **[2] [E-797](../../enhancements_doc/Enhancement-797.md) (D2).** `.save @n1[opvar]` no longer
  warns "has no value yet". The deck is correct.
- **[3] [E-798](../../enhancements_doc/Enhancement-798.md) (D3).** `print` shows a string
  parameter, `@t3m[mode] = lin`. An expression that meets one is told what it is.
- **[4] [E-799](../../enhancements_doc/Enhancement-799.md) (D4).** A value out of a paramset
  member's range names the sibling member that takes it, and how to bind there.
- **[5] [E-800](../../enhancements_doc/Enhancement-800.md) (D5).** `.temp 0 27 50` runs at 0 °C
  and says how to run each temperature.
- **[6] D6, kept as designed.** `@(timer(0, ...))` fires once at t = 0 in an equilibrium analysis
  (op, the first point of a dc sweep), the state the transient starts from. A timer that starts
  later never fires there.
- **[7] [E-801](../../enhancements_doc/Enhancement-801.md) (D7).** `pz` names a missing or wrong
  keyword, with the syntax.
- **[8] [E-802](../../enhancements_doc/Enhancement-802.md) (D8).** A batch run whose `.control`
  block ran the analyses prints each `.meas` once, and a `.meas` result is a vector.
- **[9] [E-803](../../enhancements_doc/Enhancement-803.md) (D9).** `osdi` alone lists the loaded
  libraries and their modules. Unknown options, and `-f`/`-va` with no file, are refused.
- **[10] [E-804](../../enhancements_doc/Enhancement-804.md) (D10).** A parameter set twice on a
  `.model` card: the message says the last value is used, and it is, for instance-parameter
  defaults too.
- **[11] [E-805](../../enhancements_doc/Enhancement-805.md) (D11).** Too many nodes on an OSDI line
  names the model's terminals and the nodes left over.
- **[12] [E-806](../../enhancements_doc/Enhancement-806.md) (D12).** A Verilog-A child's internal
  node answers to `n1#c1.mid` as well as the flattened `n1#c1__mid`. This holds for `print`,
  `.save`, `.meas`, `.ic` and `.nodeset`. A vector holding a subcircuit instance answers to its
  short form, `onoise_x1.n1_thermal`.
- **[13] [E-807](../../enhancements_doc/Enhancement-807.md) (D13).** `altermod nch g=7m` reaches
  every bin `nch.1`, `nch.2`.
- **[14] [E-808](../../enhancements_doc/Enhancement-808.md) (D14, D15).** The currents
  `.options savecurrents` adds stay out of ac, sp and noise plots, with a note pointing to
  `.probe i(<device>)`.
- **[15] [E-809](../../enhancements_doc/Enhancement-809.md) (D16).** An interval measurement
  whose TO lies past the end of the data says the window was cut.
- **[16] [E-810](../../enhancements_doc/Enhancement-810.md) (D17).** A saved OSDI opvar is typed
  by its declared units.

Run: `python3 verify_osdislips.py` (93 checks per solver, both solvers; 60 fail on the E-795
binaries, none of them in [6]).
