# tempguard_examples — Enhancement-815

[E-815](../../enhancements_doc/Enhancement-815.md), F24 of the
[2026-10-08 ngspice + OSDI hunt](../../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
`alter n1 dtemp=-400` printed "the offset is ignored", and the model was evaluated at
-99.85 K all the same. Only `OSDIsetup` guarded the composed temperature; `OSDItemp`, which
runs for every later analysis and sweep point, did not. `dt=-400` on the line, a `.dc` sweep
of the knob, and a later ambient change reached the model too, and a built-in device took the
values silently. The module `$strobe`s the temperature it is evaluated at, so every check reads
what the model saw.

- **[1]** The instance line: `dtemp`, `dt` and `temp` below 0 K are refused.
- **[2]** `alter` (`dtemp`, `dt`, `temp`, `@n1[dtemp]=`): not applied, and the previous value
  is kept and reported.
- **[3]** A physical value through `alter` or a sweep still applies.
- **[4]** A built-in resistor: `alter` is refused the same way.
- **[5]** Sweeps:
  - `.dc` sweeps of `@n1[dtemp]`, `@n1[temp]` and `@r1[dtemp]` through 0 K are refused;
  - one whose `stop` is unphysical but whose last point is not still runs;
  - the `sweep` command records a refused point as NaN.
- **[6]** A later ambient makes a valid offset unphysical: the device runs at the circuit
  temperature, with one warning, and returns to the offset when the ambient allows.

Run: `python3 verify_tempguard.py` (18 checks per solver; 13 fail on the E-813 binaries).
