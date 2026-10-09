# opvarmult_examples — Enhancement-814

[E-814](../../enhancements_doc/Enhancement-814.md), F23 of the
[2026-10-08 ngspice + OSDI hunt](../../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
LRM 3.2.1: an output variable declared `(* multiplicity="multiply" *)` is reported multiplied by
`$mfactor`, one declared `"divide"` divided by it, and `"none"` (the default) as it is.
openvaf-r read the attribute nowhere, so with `m=4` every operating-point current, conductance
and capacitance of the standard models (BSIM-CMG/BULK/IMG, PSP, MEXTRAM, HICUM, HiSIM, ...)
was reported per device, and every resistance four times too large. The compiled model now
stores the scaled report. The variable the model reads keeps the per-device value.

- **[1]** `m=4`:
  - multiply and divide, from a computed value, a constant and a parameter;
  - no attribute and `"none"` unscaled;
  - `show`;
  - a variable carrying a hidden state is not fed its own report.
- **[2]** No `m`, `alter n1 m=2`, and a `.save` vector in a transient.
- **[3]** Composition: a subcircuit's `m=3`, a paramset's `.$mfactor = 8`, and Verilog-A
  children under `#(.$mfactor(4))` and `#(.$mfactor(2))`.
- **[4]** `m=0`: 0 and infinity.
- **[5]** Five attributes that cannot take effect, each warned at compile time.
- **[6]** HICUM L0 from `VA_TEST` at `m=3` against `m=1`.

Run: `python3 verify_opvarmult.py` (14 checks per solver; 13 fail on the E-813 binaries).
