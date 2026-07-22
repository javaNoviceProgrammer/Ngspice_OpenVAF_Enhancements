# wildparam_examples — Enhancement-284

Reported from real use: a Verilog-A parameter `L_um` would not sweep as
`sweep @*[[L_um]]`, and ngspice reported `'l_um'` -- which looks like the mixed-case
name was mangled by ngspice's case-insensitive netlist tokens.

Case is a red herring: the OSDI lookup **is** case-insensitive (`@*[L_UM]` resolves
`L_um`). The real cause is a LEVEL mismatch -- `@*[[param]]` / `@#*[param]` is the
INSTANCE wildcard, and a plain `parameter real L_um` in Verilog-A is a MODEL parameter
(an instance parameter needs `(* type = "instance" *)`). The old message never said so.

Fix:
- a probe `if_hasparam_wildcard()` lets a wildcard that matched nothing check the other
  level and name the form that works, in both directions;
- `sweep`'s banner classifies the knob from the name token (`sw_knobdesc()`), so an
  instance wildcard is no longer labelled `(model param)`.

## Verify

```
python3 verify_wildparam.py
```

Eight checks on a model with mixed-case `Wavelength` (model) and `L_um` (instance):
both cross-level hints name the right form; a truly absent parameter gets no bogus
hint; sweep labels both wildcard kinds correctly; the matching wildcard still sweeps
correctly; ALL-CAPS `@*[[L_UM]]` still resolves `L_um`.
