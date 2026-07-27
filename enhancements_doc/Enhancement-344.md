# Enhancement-344 — `.model` params take the fast sweep's direct set

The `.param` fast sweep (Enhancement-320 … 323) resolves each swept device value
to a slot **once** and pushes it with `ft_sim->setInstanceParm`, skipping the
per-point `reset`. Model parameters were the one tier left out. Enhancement-320
recorded it plainly:

> Model params use the textual `altermod` fallback, not the direct set.

This closes that gap. **Model params now cost exactly what instance params
cost** — they were 2.1×–2.8× slower.

---

## What was happening

A captured bind carried a ready-made textual command, and model binds used it on
every point:

```c
b->rok = 0;
if (!ckt || b->mod)          /* model binds: give up, stay textual */
    return;
```

so each point ran `altermod <model> <param> = <value>` through `sw_run_cmd()`.
That re-does, per point and per model:

- `snprintf` the command, then `cp_lexer()` it into a wordlist;
- `com_altermod` → `com_alter_common` → argument re-parse;
- `finddev()` → resolve the model **by name**;
- walk the model's parameter table matching `keyword` by string;
- and finally the `setModelParm` that was the only part that mattered.

Everything above the last line is re-derived work that cannot change between
points — exactly what E-320 removed for instances.

## The fix

`sw_fp_resolve()` now resolves model binds too, to `(GENmodel *, type,
param-id)`, and `sw_fp_apply()` pushes them with `ft_sim->setModelParm`:

```c
if (b->mod)                  /* Enhancement-344: model tier */
    ft_sim->setModelParm(ckt, b->modp, b->parmid, &val, NULL);
else
    ft_sim->setInstanceParm(ckt, b->inst, b->parmid, &val, NULL);
```

The parameter-table search that instance binds already used was factored into
`sw_fp_find_parm()` and is now shared, so both tiers apply the same rules:
`IF_SET`, `IF_REAL`, keyword match (or the positional principal, which only
instances have — a `.model` line has no principal slot).

Anything that does not resolve — a model that is not built, or a parameter that
is not a settable real, such as an integer `level` — leaves `rok = 0` and keeps
its textual command. **The fallback is not dead code**; it is the correctness
backstop, and one of the example's checks exercises it deliberately.

Model binds are marked in `touched[]` like instance binds, so a touched device
type still gets its one `DEVtemperature` refresh per point.

### The banner now says when a bind did not take the direct path

```
sweep: fast .param path armed (1 value binding, no per-point reset)
sweep: fast .param path armed (1 value binding, no per-point reset), 1 via alter/altermod
```

The suffix appears only when something fell back. Ordinary output is unchanged,
and a slower textual push no longer hides behind the same banner as a direct one.

---

## This is a speed change, not a correctness fix

Worth stating explicitly, because it shaped how it was verified: **the textual
path was already correct.** Before writing any code, it was checked against the
reset path on a semiconductor resistor and on a compiled OSDI model, and matched
exactly in both. There was no bug here — only wasted work.

That makes "identical to the reset path" the whole acceptance criterion.

### Measured

`sweep` over a deck of N models, 200 points, same binary:

| models | textual (shipped) | direct (new) | speedup | vs. an equivalent instance-param sweep |
|---|---|---|---|---|
| 50 | 0.034 s | 0.016 s | **2.1×** | was 2.1× slower → now **1.0×** |
| 200 | 0.095 s | 0.034 s | **2.8×** | was 2.8× slower → now **1.0×** |

At a larger scale, and against the reset path it replaces:

| deck | reset | textual fast | direct fast | vs. textual | vs. reset |
|---|---|---|---|---|---|
| 400 R models, 400 pts | 0.87 s | 0.36 s | **0.12 s** | 3.1× | 2.4× → **7.5×** |
| 60 OSDI models, 400 pts | 0.12 s | 0.07 s | **0.03 s** | 2.2× | 1.7× → **4.0×** |

The `model/instance` ratio landing exactly on 1.00× is the real result: it says
the model tier now does the same work per point as the instance tier, with no
residual per-point resolution left.

### Correctness

A 12-case battery, each run twice — fast path and reset path — and compared:

| | |
|---|---|
| resistor `rsh`, resistor `tc1` | exact |
| capacitor `cj`, diode `is` | exact |
| MOSFET `vto`, BJT `bf` | exact |
| OSDI model `r` | exact |
| two models sharing one swept param | exact |
| model + instance binds in one sweep | exact |
| swept param via a derived `.param` | disarms (as before), exact |
| non-real (integer) model param | falls back to textual, exact |

Plus subcircuit-internal models (the E-321 tier): a model declared inside a
`.subckt` and instantiated twice arms and is exact, while a subcircuit that
locally shadows the swept name correctly disarms and still matches reset.

The `optimize` tier shares this engine (E-322), so `-mparam` inherits the direct
set for free; `examples/optimize_examples` passes 43/43 unchanged.

Full regression: 276/276 OK. Example: `examples/modelparamset_examples/`, 7
checks, agreeing with closed form to 1e-10 (the deck raises `numdgt` so the
comparison is not capped by the default 7-digit print).

---

## Still not done

**Monte Carlo.** Unchanged, and it is not the same kind of problem: MC needs a
re-*draw* of process variation, not a deterministic value push, so it is a
different mechanism rather than another tier of this one.

With models done, every deterministic `.param` → device/model value path — top
level, subcircuit, instance, model, sweep and optimize — now takes the direct
set.
