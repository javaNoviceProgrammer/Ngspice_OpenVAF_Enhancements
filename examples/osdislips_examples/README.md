# osdislips_examples — Enhancements 796 to 804

The smaller slips D1 to D10 of the
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

Run: `python3 verify_osdislips.py` (56 checks per solver, both solvers; 35 fail on the E-795
binaries, none of them in [6]).
