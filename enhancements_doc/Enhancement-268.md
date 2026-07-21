# Enhancement-268 — ngspice: wildcard model-parameter knob `@*[param]`

Multiple `.model` cards can share a model-parameter **name** — e.g. two Verilog-A
models `.model dev1 model1` and `.model dev2 model2` that both declare a
`wavelength` parameter. Before this change there was no way to sweep that shared
parameter across all such models in a single knob:

- `sweep @dev1[wavelength] …` (`altermod`) targets **one** model only.
- The `.param` idiom (`.param wl=…`, `wavelength={wl}` in each card,
  `sweep wl …`) does work, but a `.param` knob commits with `reset`, which
  **re-sources the entire deck at every sweep point** — slow, and it needs the
  model cards to reference the shared param.

## The wildcard knob

`@*[param]` sets `param` on **every loaded model that has it**, in place (via
`altermod`, no deck re-source):

```spice
sweep @*[wavelength] 1.30u 1.60u 0.01u -output ...
```

co-varies `wavelength` across `dev1`, `dev2`, and any other model that carries a
`wavelength` parameter — one sweep, no `reset`. It also works as a standalone
command:

```spice
altermod @*[wavelength]=1.55u
```

## Implementation

- **`spiceif.c` — `if_setparam_wildcard(ckt, param, val)`**: model parameters are a
  property of the device *type*, so one `parmlookup` per device type decides
  whether that type's models carry `param`; every model of a matching type
  (walking `ckt->CKThead[typecode] → GENnextModel`) is then set with `doset` — the
  same path a concrete `altermod @model[param]=` uses. Returns the count set, and
  (like `if_setparam`) runs `CKTtemp` to push the change into live instances when
  called mid-run. Models without the parameter, and unrelated device types, are
  skipped.
- **`device.c` — `com_alter_common`**: a wildcard device name `@*` routes to
  `if_setparam_wildcard`; a concrete `@model[param]` or device is unchanged. If no
  loaded model has the parameter, a single clear warning is printed.
- **`com_sweep.c` — `sw_kind`**: `@*[param]` is classified as an in-place
  `altermod` knob (like `@model[param]`), so the sweep applies it without a
  `reset`. `com_sweep.h`/`fteext.h` carry the new prototype.

## Verification

`examples/sweepwild_examples/verify_sweepwild.py` (4 checks, both solvers): a
circuit with two `wlmodel` cards (R = wavelength·1k) plus one unrelated model
without `wavelength`. `sweep @*[wavelength]` co-varies **both** `wlmodel` devices
(equal currents tracking `1/(wavelength·1k)`); the unrelated model is untouched; a
concrete `@dev1[wavelength]` still targets only `dev1`; and `@*[<absent>]` warns
and changes nothing. Full dual-solver example regression passes.

## Scope

Four files (`spiceif.c`, `device.c`, `com_sweep.c`, `fteext.h`). Additive: no
existing `alter`/`altermod`/`sweep` behaviour changes; `@*` was previously not a
valid model name.
