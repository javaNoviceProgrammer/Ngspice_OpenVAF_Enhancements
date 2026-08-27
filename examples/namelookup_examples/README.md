# Enhancement-493 — three names the simulator would not look up

```
python3 verify_namelookup.py
```

39 checks, a few seconds. **29/39** against the pre-fix binary — **10**
checks discriminate.

## What it is

One shape, three times: **a name the user wrote was not looked up where it was
written, and what came back described something else.**

## 1. `showmod` could not be handed a model name

| | |
|---|---|
| `showmod d1` (the *device*) | prints the model |
| `showmod #dm` (explicit) | prints the model |
| `showmod dm` (the *model*) | **"No matching instances or models"** |

The command's own help calls its argument *"models"*, and its write sibling
`altermod dm is=1e-12` takes the model name directly. **OSDI models were affected
identically** — the defect is in the name grammar, not in any device.

## 2. A saved name that matched nothing was dropped in silence

```
.save v(n) v(nosuch)     →  records v(n), drops the typo, says nothing
```

`.probe v(nosuch)` shares that path — which is why a mistyped **node** was silent
while a mistyped **source** in the same card is reported, and why
[E-418](../../enhancements_doc/Enhancement-418.md) already spoke for the
`@dev[param]` spelling.

## 3. A resistor model named `r` was unreachable

`.model r r rsh=1k` with `R1 a 0 r l=1u w=1u` bound neither model nor value; the
device came out **1 mΩ** with *"resistance too low or not given"* — the symptom,
not the cause. Only this one letter: `rsh`, `l`, `w`, `tc1`, `temp`, `m` and
`scale` all work as model names.

## The controls

Well over half the suite pins what must **not** move, because each fix sits in a
lookup that everything else uses:

* `showmod` by device name, by `#model`, and bare; `show`; `altermod`.
* A name that is neither a device nor a model still reports exactly as before.
* `.save all` / `.save allv` / `.probe alli`, items belonging to another
  analysis, and `@dev[param]` saves — never flagged as unmatched.
* A real node saved under `op`, `ac`, `dc` and `tran`.
* `r=1k`, `r = 1k`, `R=2k`, a plain value, `r=1k tc1=0`, a value with `m=`, and
  **`r=4k` winning when a model named `r` also exists**.

## The model

`namelookup.va` holds one module, `nlk`, used to show that reaching a model by
name is not a built-in-device special case: `showmod mm` reported "No matching"
for an OSDI model too, while `showmod n1` printed it.
