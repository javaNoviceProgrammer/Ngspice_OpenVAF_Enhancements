# Enhancement-436 — one model name, every instance path

```
altermod @*:rmod[res]=3000       rmod, x1:rmod, x2:rmod, x1.x2:rmod, …
sweep    @*:rmod[res] 1k 3k 1k   all of them, together
```

Subcircuit expansion renames a `.model rmod` inside instance `x1` to `x1:rmod`.
So a deck that declares `rmod` at top level *and* inside a subcircuit ends up
with several distinct models, and before this change there were exactly two ways
to reach them — one too narrow, one too wide:

| | reaches | |
|---|---|---|
| `@rmod[res]` | the top-level card **only** | every subcircuit copy silently keeps its old value |
| `@*[res]` | every model that has `res` | sweeps up unrelated models too |

Neither expresses *"the model called `rmod`, wherever it lives"*, which is the
ordinary thing to want: one model definition, instantiated several times, plus a
top-level copy.

## The new form

`@*:rmod[param]` — the `*` stands for the **instance path**, and matches any
path **including none**, so the top-level card is covered alongside every
`<path>:rmod`. Matching is on the leaf name — everything after the last `:`, the
whole name when there is none — which makes it depth-independent: `rmod`,
`x1:rmod` and `x1.x2:rmod` all match, with no pattern syntax involved.

`@*.rmod[param]` is accepted identically, since Enhancements 433 and 435 taught
the dotted spelling everywhere else and it is what people type.

It is deliberately **not** a glob. `@x*:r*` stays an error. Enhancement-269's
wildcards are a small fixed token set, a mistyped pattern would match nothing
silently, and every command that resolves a model name would have to agree on
the rules.

## Why `@rmod` was not simply broadened

The obvious alternative — make a bare `@rmod[param]` reach every copy — was
rejected. It would change what existing decks do with no diagnostic: a deck that
today adjusts only the top-level card would suddenly adjust every instance, and
results would move. Every hierarchical fix in this project (E-410, E-428, E-433,
E-435) was safe precisely because it could only turn an *error* into a hit, never
one working behaviour into a different working behaviour. Targeting a single
card also has to stay reachable — it is exactly what mismatch work needs.

What was missing was not reach but **information**, so the confusing case now
speaks:

```
altermod @rmod[res]=3000
    Note: 3 models are named 'rmod' (the top-level card and 2 flattened
    subcircuit copies); only the top-level one was changed -- use
    '@*:rmod[...]' for all of them.
```

Two failure messages tell the two failures apart, rather than a shared
"not found":

```
@*:nosuch[res]   -> no loaded model is named 'nosuch' (a model inside a
                    subcircuit is flattened to <instance>:nosuch)
@*:rmod[nosuchp] -> no model named 'rmod' has parameter 'nosuchp'
```

## Where it lives

`if_setparam_wildcard_model_named()` in `spiceif.c` walks the same model lists as
the existing `if_setparam_wildcard()` and filters on the leaf name;
`if_hasmodel_named()` supports the diagnostics. `alter_set()` in `device.c`
dispatches the new token, and `sw_kind()` in `com_sweep.c` classifies it as a
model knob so `sweep` routes it to `altermod`, where the matching lives.

## A gap that turned out not to exist

The instance wildcards `@#*[param]` and `@*[[param]]` appeared not to reach
inside subcircuits. They do. The probe that suggested otherwise measured a
voltage divider in which the wildcard changed *both* resistors equally, so the
ratio stayed 0.5 and nothing looked like it had moved. Reading the parameter back
settles it — `r.x1.rx` and `r.x2.rx` go 1000 → 3000 exactly as the top-level
resistor does — and the implementation agrees: `if_setparam_wildcard_instance()`
walks every device type, model and instance in the circuit, and flattened
subcircuit instances are ordinary members of those lists.

## Verification

* **`examples/modelwild_examples` — 11/11.** The deck is built so every level of
  reach is distinguishable: `v(a)`/`v(b)` are driven by the two subcircuit
  copies, `v(e)` by the top-level card, and `v(c)` by an unrelated `omod` that
  must not move. Both spellings of the new form are checked, the two existing
  forms are checked to be **unchanged**, `sweep` is checked on a subcircuit copy
  and on the top-level card in the same sweep, and both diagnostics are pinned.
* **Full regression 347/347**, both solvers.

## Found by

The question *"how do I sweep the parameter of one particular model inside all
subcircuit instances — and also at the top level?"* The answer was that you
could not, other than by naming every instance by hand; and the follow-up
requirement to include the top-level card is what fixed the semantics of `*` as
"any path, including none".
