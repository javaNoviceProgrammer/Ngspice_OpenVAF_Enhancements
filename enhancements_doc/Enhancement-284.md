# Enhancement-284 — ngspice: wildcard parameter diagnostics, and the `sweep` knob label

Reported from real use: a Verilog-A parameter `L_um` could not be swept as
`sweep @*[[L_um]]`, and ngspice's message named `'l_um'` — which reads like the
mixed-case name had been mangled by ngspice's case-insensitive netlist tokens.

## The bug

The case theory is a red herring — the OSDI parameter lookup **is** case-insensitive
(`@*[L_UM]` resolves `L_um` correctly). The real cause is a level mismatch, and the
diagnostics hid it:

1. `@*[[param]]` (and `@#*[param]`) is the **instance** wildcard. A plain
   `parameter real L_um` in Verilog-A is a **model** parameter — an instance parameter
   needs `(* type = "instance" *)`. So the instance wildcard correctly matched nothing
   and reported `no loaded instance has parameter 'l_um'`: lower-cased, with no hint
   that the parameter exists at the *model* level. Nothing pointed at the fix.
2. `sweep` labelled every knob it applies in place as `(model param)` — including the
   instance wildcards — because `sw_kind()` returns `SW_MODEL` as a *dispatch* flag
   (meaning "apply via `altermod`, no re-source"), and the banner reused that flag as
   a description.

## Fix

- **`spiceif.c`** — a new probe `if_hasparam_wildcard(ckt, param, do_model)` reports
  whether any loaded model (or instance) carries a settable parameter of that name.
  It only probes; nothing is changed.
- **`device.c`** — when a wildcard matches nothing, it now checks the other level and
  names the form that would work, in both directions:
  - *"no loaded instance has parameter 'l_um', but a loaded model does — use the model
    wildcard '@\*[l_um]' (an instance parameter needs (\* type = "instance" \*) in the
    Verilog-A)."*
  - *"no loaded model has parameter 'l_um', but a loaded instance does — use the
    instance wildcard '@#\*[l_um]'."*
  A parameter that genuinely does not exist still gets the plain message, with no
  misleading suggestion.
- **`com_sweep.c`** — `sw_knobdesc()` classifies the knob from the **name token**, so
  the banner reads `(instance param, wildcard)` for `@#*[…]` / `@*[[…]]` and
  `(model param, wildcard)` for `@*[…]`.

## Verification

`examples/wildparam_examples/verify_wildparam.py` (8 checks), on a model with a
mixed-case model parameter `Wavelength` and a mixed-case instance parameter `L_um`:
both cross-level hints appear and name the right form; a truly absent parameter gets
no bogus hint; `sweep` labels instance and model wildcards correctly; the matching
wildcard still sweeps to the right values; and ALL-CAPS `@*[[L_UM]]` still resolves
the mixed-case `L_um`, confirming the lookup was never case-sensitive.

## Scope

Four files (`spiceif.c`, `fteext.h`, `device.c`, `com_sweep.c`). Diagnostics and one
banner string; no change to which parameters any wildcard actually sets.
