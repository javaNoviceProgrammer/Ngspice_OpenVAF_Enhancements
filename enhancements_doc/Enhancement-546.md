# Enhancement-546: a parameter that reads an instance parameter is resolved per instance

**Scope:** finding F2 of the compiler hunt
([`docs/bug_hunts/2026-09-04_openvaf-r-compiler.md`](../docs/bug_hunts/2026-09-04_openvaf-r-compiler.md)).
**Compiler only; ngspice is unchanged.**

**Suites:** [`instdep_examples`](../examples/instdep_examples/) (new, 20
checks); sim_back unit test `instance_dependent_parameters`. Handbook
[§2](../docs/handbook/02-verilog-a-language.md) row *Instance-line
parameters*; compiler internals Chapter 9.

## What was wrong

The model/instance split — `(* type="instance" *)` — is an OpenVAF
convention, not a language one: in Verilog-A every parameter belongs to the
instance, and a "model" parameter is one the compiler may resolve *once per
model card* because nothing in it varies between the card's instances. This
broke the premise, and the back end did not notice:

```verilog
(* type="instance" *) parameter real w = 1e-6 from (0:inf);
parameter real l = 1e-6 from (0:w];
```

`l` was resolved in the model setup with the card-level `w` — the declared
default unless the card gave one — stored in the model, and every instance
read that value.

| deck | before | after |
|---|---|---|
| `.model mm m(l=1e-6)`, `n2 … w=0.5e-6` | **ran**, l/w = 2.0 (the range says l ≤ w) | refused: `l` of `n2` out of bounds |
| `.model mm m(l=3e-6)`, `n1 … w=5e-6` | **refused**, against the default w | runs, l/w = 0.6 |
| `parameter real l = 2*w;`, `n1 … w=3e-6` | l = 2e-6 | l = 6e-6 |

## What changed — two dependences, two treatments

Module collection (`sim_back::module_info::promote_instance_dependent`)
follows every parameter's default and bounds — through the user functions a
default calls and through function-local parameters, with `$param_given(p)`
counting as a read of `p` (`BodyRef::param_reads_and_calls` walks the
inference result, so it is total) — and decides:

* **A default that reads an instance parameter** gives the parameter a value
  per instance, so it is **promoted** to instance level and the whole back
  end follows: instance storage, the per-instance resolution and range check
  in `setup_instance`, the OSDI parameter table. It stays settable on the
  `.model` card as the default for the card's instances. The new
  `instance_dependent_parameter` lint (L028, warn) names every promotion
  except that of an untyped `localparam`, where per-instance resolution is
  the only meaning the declaration could have;
  `(* openvaf_allow="instance_dependent_parameter" *)` accepts it silently
  and `(* type="instance" *)` states the intent.
* **A range that reads an instance parameter** does not change what the
  parameter is. The stock CMC models are full of this shape — BSIM6,
  BSIMBULK and BSIMIMG `XGL from (-inf:L*LMLT+XL)`, BSIMBULK `LH from (0:L)`,
  HiSIM2 `LP from [0:L]`, HiSIMHV `RDRDL1/2`, HiSIMSOTB `PARL1/2`: twelve
  parameters in ten models — and promoting them would have rewritten their
  parameter tables for a range check. Such a parameter keeps its level and
  is marked `instance_bounds`: the model setup skips its given-value check
  (`unchecked` in `HirInterner::insert_param_init`) and the instance setup
  judges it with the instance's values — while resolving it, for an instance
  parameter; as a check alone, for a model parameter (`check_only`), with the
  model-parameter error id routed through `setup_instance` so the simulator
  names the instance and the value.

One stock model has the default shape, and it is the bug in the wild:
**BSIMCMG declares `LSP` a model parameter with the default `0.2 * (L + XL)`**,
so every instance that did not give `LSP` ran with the default `L` folded in.
It is now resolved per instance, and L028 says so.

## Verification

| check | result |
|---|---|
| the hunt's deck: `n2` with w below the card's l | refused per instance (was: ran) |
| a card l above the default w, instance w = 5e-6 | runs (was: refused at the card) |
| `l = 2*w` with `w = 3e-6` | l = 6e-6 (was 2e-6) |
| `localparam real l2 = 2*w` | promoted silently, l2/w = 2 |
| `a = l + 1e-6` and `$param_given(w)` across two instances of one card | 7e-6 / 3e-6 and 1 / 0 |
| a parameter reading only model parameters | stays a model parameter, refused on the instance line |
| bundled industry models | 40 / 40 compile; one L028 hit, BSIMCMG `LSP` |
| compiler test suite | 215 passing (the `sourcegen` regeneration artefact aside) |
| `instdep_examples` | 20 / 20, both solvers |
| full sweep | 455 of 455 |
