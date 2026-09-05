# Enhancement-546 — a parameter that reads an instance parameter

```
python3 verify_instdep.py
```

20 checks, both solvers. Compiler hunt F2 (2026-09-04).

## The shape

The model/instance split — `(* type="instance" *)` — is an OpenVAF convention,
not a language one. In Verilog-A every parameter belongs to the instance; a
"model" parameter is one the compiler may resolve **once per model card**
because nothing in it varies between that card's instances. This broke the
premise, and the back end did not notice:

```verilog
(* type="instance" *) parameter real w = 1e-6 from (0:inf);
parameter real l = 1e-6 from (0:w];
```

`l` was resolved in the model setup with the card-level `w` — the declared
default unless the card gave one — stored in the model, and every instance
read that value.

| deck | before | after |
|---|---|---|
| `.model mm m(l=1e-6)`, `n2 … w=0.5e-6` | **ran**, l/w = 2.0 | refused: `l` of `n2` out of bounds |
| `.model mm m(l=3e-6)`, `n1 … w=5e-6` | **refused**, against the default w | runs, l/w = 0.6 |
| `parameter real l = 2*w;`, `n1 … w=3e-6` | l = 2e-6 | l = 6e-6 |

## Two dependences, two treatments

- **A default that reads an instance parameter** gives the parameter a value
  per instance, so it is **promoted** to instance level: the instance setup
  resolves it with that instance's values. The dependency is transitive
  (through other promoted parameters, through user functions a default calls,
  through function-local parameters) and `$param_given(p)` counts as reading
  `p`. The `instance_dependent_parameter` lint (L028, warn) names every
  promotion except that of an untyped `localparam`, where nothing settable
  changes; `(* openvaf_allow="instance_dependent_parameter" *)` accepts it
  silently and `(* type="instance" *)` states the intent. A promoted parameter
  stays settable on the `.model` card, like any instance parameter, as the
  default for the card's instances. One stock model has this shape, and it
  is the bug in the wild: BSIMCMG declares `LSP` a model parameter with the
  default `0.2 * (L + XL)`, so every instance that did not give `LSP` ran
  with the default `L` folded in. It is now resolved per instance.
- **A range that reads an instance parameter** does not change what the
  parameter is. The stock CMC models are full of this shape — BSIM6's
  `XGL from (-inf:L*LMLT+XL)`, HiSIM2's `LP from [0:L]`, twelve parameters in
  ten models — and promoting them would rewrite their parameter tables for a
  range check. The parameter keeps its level; the model setup skips its
  given-value check and the instance setup judges it with the instance's
  values. Nothing is said.

## What the checks pin

| checks | what |
|---|---|
| 1–5 | the hunt's range shape: judged per instance in both directions, `l` staying a model parameter |
| 6–7 | the default shape: `parameter` promoted and named, untyped `localparam` promoted silently, both reading the instance's `w` |
| 8–10 | the lint's wording for an explicit `type="model"`, the allow attribute, a typed localparam |
| 11–12 | transitivity and `$param_given`: two instances of one card differ |
| 13–14 | a promoted parameter given on the card and per instance; a parameter reading only model parameters stays on the model |
| 15–16 | a declared instance parameter whose bounds read another instance parameter |
| 17–18 | a model parameter whose range reads a promoted parameter |

Where it lives: `sim_back::module_info::promote_instance_dependent` (the
classification), `HirInterner::insert_param_init` (`unchecked` for the model
setup, `check_only` for the instance setup), `osdi::setup::setup_instance` (the
model-parameter error id).
