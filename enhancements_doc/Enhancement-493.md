# Enhancement-493 — three names the simulator would not look up

**Files:** `src/frontend/device.c`, `src/frontend/outitf.c`,
`src/spicelib/parser/inp2r.c`.

**Suite:** `examples/namelookup_examples/` — 39 checks.

## Why

Round 53 found the same shape three times: **a name the user wrote was not looked
up where it was written, and what came back described something else.**

## 1. `showmod <model name>` could not find the model

The device generator's grammar reads a bare word as an **instance** name, and only
a `#`-prefixed one as a **model** name. So with `.model dm d` used by `D1`:

| | |
|---|---|
| `showmod d1` (the *device*) | prints the model |
| `showmod #dm` (explicit) | prints the model |
| `showmod dm` (the *model*) | **"No matching instances or models"** |

— of a model that plainly exists. The command's own help calls its argument
*"models"*, and its write sibling takes the model name directly (`altermod dm
is=1e-12` works), so the one command dedicated to models was the one that could
not be handed one. It affects **OSDI models identically**, because the defect is
in the name grammar rather than in any device.

**Retry rather than reinterpret.** The bare-name-is-an-instance reading runs first
and unchanged, so `showmod d1` — and any name that is both a device and a model —
behaves exactly as before. Only when *nothing* matched is each bare word retried
with the `#` the grammar wants, and a name that is neither ends at the same
message it always did.

## 2. A saved name that matched nothing was dropped in silence

Pass 1 of the output setup walks each `.save`/`.probe` item against the analysis's
own vector names and marks the ones it places; anything it failed to match simply
stayed unmarked and the run continued without it:

```
.save v(n) v(nosuch)     →  records v(n), drops the typo, says nothing
```

The analysis succeeds and the vector the user asked for is merely absent.
`.probe v(nosuch)` reaches the same path — which is why a mistyped **node** there
was silent while a mistyped **source** in the same card is reported by the
measure-source pass (*"Could not find the instance line for …"*), and why
Enhancement-418 already said it for the `@dev[param]` spelling (*"no such device,
so this vector will stay empty"*). The plain node spelling was the one route left
quiet.

It **warns** rather than refuses: an absent vector is not a wrong answer, and a
deck that saves a node it does not always build is a real idiom. The check honours
`savesused[]` first — so the `all`/`allv` keywords and items belonging to another
analysis are never reported — and falls back to matching the name itself under
`save all`, which `.probe` turns on and where Pass 1 never runs.

## 3. A resistor model named `r` was unreachable

`INP2R` excluded the token `r` from being a model name outright:

```c
if (*model && (strcmp(model, "r") != 0)) {
```

That exclusion is necessary for `R1 a b r=1k`, where `r` is the keyword that
writes the resistance and must not be read as a model. But it also locked out a
model actually **called** `r`: `.model r r rsh=1k` with `R1 a 0 r l=1u w=1u` bound
neither model nor value, so the device fell through to the default and came out as
**1 mΩ** with *"resistance too low or not given"* — a message about the symptom,
when the cause is that the model named on the line was never looked up.

Every other name works, including every other resistor keyword — `rsh`, `l`, `w`,
`tc1`, `tc2`, `temp`, `dtemp`, `m`, `scale`, `ac`, `dc`, `noisy`, `short`,
`narrow`. Only this one letter was unreachable.

The two spellings are distinguishable by what **follows** the token: the keyword
form is `r=`, a model name is not. Asking that instead keeps `r=1k` meaning what
it always did and makes a model called `r` reachable. A deck with no such model is
unaffected — `INPlookMod` fails and the existing else branch restores the line and
builds the default model, exactly as for any other unrecognised token.

## What this deliberately does not change

* **`showmod <device>`, `showmod #<model>`, bare `showmod`, and `show`** — all
  unchanged, including a name that is both a device and a model.
* **`altermod <model>`**, which already worked.
* **`.save all` / `.save allv` / `.probe alli`**, and any item belonging to
  another analysis — never reported as unmatched.
* **`@dev[param]` saves**, which Enhancement-418 already speaks for.
* **`r=1k`, `r = 1k`, `R=2k`**, a plain value, `r=1k tc1=0`, and `r=4k` winning
  when a model named `r` also exists.

## Verification

```
python3 examples/namelookup_examples/verify_namelookup.py   # 39/39
python3 examples/run_regression.py                          # 407/407
```

**29/39** against the pre-fix binary, so **10 of 39 checks discriminate**; the
other twenty-nine are controls that must not move, and do not. The ones that make
each fix easy to get wrong are among them — `showmod` by device name and by
`#model`, `.save all`/`.probe alli`, and `r=1k` still writing a resistance when a
model named `r` also exists.
