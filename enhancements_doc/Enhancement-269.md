# Enhancement-269 — ngspice: instance wildcard `@#*[param]` (and alias `@*[[param]]`)

Enhancement-268 added `@*[param]`, which sets a **model** parameter on every loaded
model that has it. This adds the **instance** counterpart: a wildcard that sets an
**instance** parameter across every device instance that has it — in place, no deck
re-source.

## Two spellings

```spice
sweep @#*[scale] 1 4 1 -output ...      # co-vary an instance parameter across ALL instances
altermod @#*[scale]=2                   # or apply it directly
alter    @*[[scale]]=2                  # @*[[param]] is an alias for @#*[param]
```

- `@#*[param]` — the canonical form (`#` marks *instance*).
- `@*[[param]]` — the same thing with the double bracket ("one level deeper, into
  instances"); accepted as an alias.

This complements `@*[param]` (model wildcard, E-268):

| knob | targets |
|---|---|
| `@*[param]` | every **model** card that has `param` |
| `@#*[param]` / `@*[[param]]` | every **instance** that has `param` |

Model wildcards and instance wildcards are distinct even when a parameter name
exists at both levels: `@*[w]` sets the model value, `@#*[w]` sets the per-instance
value. An instance that explicitly set the parameter on its device line keeps its
own value only insofar as the concrete syntax `@inst[param]` is used; the wildcard
sets *every* matching instance.

## Implementation

- **`spiceif.c` — `if_setparam_wildcard_instance(ckt, param, val)`**: instance
  parameters are a property of the device *type*, so one
  `parmlookup(…, do_model=0, …)` per type decides whether that type's instances
  carry `param`; every instance (walking each model's
  `GENinstances → GENnextInstance`) is set with `doset(dev=inst, mod=NULL)` →
  `setInstanceParm` — the same path a plain `alter @dev[param]=` uses.
- **`device.c` — `alter_set`**: the device-name token selects the wildcard —
  `@#*` (token `#*`), or `@*[[param]]` (token `*` with the outer parse leaving
  `param` as `[param`, whose leading `[` is stripped) → instance wildcard; `@*`
  → model wildcard (E-268); anything else → the ordinary `if_setparam`. A no-match
  wildcard prints one clear warning.
- **`com_sweep.c` — `sw_kind`**: `@#*[param]` (and `@*[[param]]`, whose token scans
  to `*`) are classified as in-place `altermod`-style knobs, so the sweep applies
  them without a `reset`. Prototype in `fteext.h`.

## Verification

`examples/sweepwild_examples/verify_sweepwild.py` (7 checks, both solvers), using a
`wlmodel` with a **model** parameter `wavelength` and an **instance** parameter
`scale` (R = wavelength·scale·1k): the model wildcard co-varies both model cards and
**reaches `.model` cards inside subcircuits** (they flatten to per-instantiation
model copies); the instance wildcard `@#*[scale]` co-varies every instance, as does
the alias `@*[[scale]]`; concrete `@dev1[wavelength]` / `@NX2[scale]` still target
just their own device; and `@*[<absent>]` / `@#*[<absent>]` warn and change nothing.
Full dual-solver example regression passes.

## Scope

Four files (`spiceif.c`, `device.c`, `com_sweep.c`, `fteext.h`), extending the E-268
wildcard machinery. Additive — `@#*` / `@*[[…]]` were not previously valid names.
