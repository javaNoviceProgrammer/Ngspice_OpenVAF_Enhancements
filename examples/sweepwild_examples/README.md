# sweepwild_examples — Enhancement-268

The wildcard model-parameter knob **`@*[param]`** sets a model parameter on
**every loaded model that has it**, in place (`altermod`, no deck re-source). This
lets one `sweep` co-vary a shared parameter across several `.model` cards:

```spice
sweep @*[wavelength] 1.30u 1.60u 0.01u -output ...
```

Before, `sweep @dev1[wavelength]` targeted one model only, and the `.param` idiom
worked but re-sourced the whole deck at every point (slow). `@*[param]` is applied
in place — no `reset`. It also works standalone: `altermod @*[wavelength]=1.55u`.

Models without the parameter (and unrelated device types) are skipped; `@*[<absent
param>]` prints a warning and changes nothing. A concrete `@model[param]` is
unchanged.

`wlmodel.va`: R = `wavelength`·1k. The verify instantiates two `.model` cards of it
plus one unrelated model (no `wavelength`).

## Verify

```
python3 verify_sweepwild.py
```

Four checks (both solvers): `sweep @*[wavelength]` co-varies both `wlmodel`
devices; the unrelated model is untouched; a concrete `@dev1[wavelength]` targets
only `dev1`; `@*[absent]` warns and changes nothing.
