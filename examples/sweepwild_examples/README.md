# sweepwild_examples — Enhancement-268 / -269

Wildcard parameter knobs that set a parameter on **every** matching model or
instance, in place (`altermod`/`alter`, no deck re-source) — so one `sweep` can
co-vary a shared parameter without the slow `.param` + `reset` idiom:

| knob | targets | enhancement |
|---|---|---|
| `@*[param]` | every **model** card that has `param` | E-268 |
| `@#*[param]` | every **instance** that has `param` | E-269 |
| `@*[[param]]` | alias for `@#*[param]` | E-269 |

```spice
sweep @*[wavelength] 1.30u 1.60u 0.01u -output ...   # model parameter, all models
sweep @#*[scale]     1 4 1              -output ...   # instance parameter, all instances
altermod @*[wavelength]=1.55u                         # also work standalone
alter    @#*[scale]=2
```

Models/instances without the parameter (and unrelated device types) are skipped;
`@*[<absent>]` / `@#*[<absent>]` warn and change nothing. A concrete `@model[param]`
or `@inst[param]` is unchanged. The model wildcard also reaches `.model` cards
**inside subcircuits** (they flatten to per-instantiation model copies).

`wlmodel.va`: R = `wavelength`·`scale`·1k, where `wavelength` is a **model**
parameter and `scale` an **instance** parameter — so the verify exercises both
wildcard kinds against one model.

## Verify

```
python3 verify_sweepwild.py
```

Seven checks (both solvers): model wildcard co-varies both model cards; it reaches
subcircuit-internal models; the instance wildcard `@#*[scale]` and its alias
`@*[[scale]]` co-vary every instance; concrete knobs target one device; absent-param
wildcards warn.
