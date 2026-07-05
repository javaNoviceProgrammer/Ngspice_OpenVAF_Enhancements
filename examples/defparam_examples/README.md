# defparam_examples — hierarchical parameter override (Enhancement-58)

Demonstrates **`defparam`** — the legacy Verilog-2001 compile-time
parameter override (LRM 2.6) — using the committed `openvaf-r` and
`ngspice-46`.

## What was broken

`defparam` did not parse at all: it was a reserved word with **no grammar
rule**, so `defparam u1.r = 2e3;` produced the misleading error
`'defparam' was not found in the current scope`. (The idiomatic instance
overrides `#(.r(2e3))` and `#(2e3)` already worked; `defparam` is the
deprecated hierarchical-override form.)

## What now works

- **`DEFPARAM_KW`** is a keyword token with a parser rule producing a
  `DEFPARAM` syntax node — deliberately **not** a typed `ModuleItem`, so the
  later compiler stages (hir_def onward) never see it; it is consumed
  entirely by the E-5 elaboration pass.
- Each `defparam` target is resolved through the **same instance-chain
  rewrite E-49 uses** for hierarchical references: `u1.r → u1__r`,
  `u1.u2.r → u1__u2__r` — exactly the flattened name the target parameter
  is given when its instance is inlined — and the flattened parameter's
  default is rewritten.
- `defparam` has **higher precedence than an instance `#(...)` override**
  (LRM 2.6): `dp_leaf #(.r(5e3)) up(...)` with `defparam up.r = 2e3` yields
  2k, not 5k.
- Multi-assignment (`defparam up.r = 2e3, up.g = 1e-3;`) and override
  expressions that reference the enclosing module's parameters
  (`defparam u1.r = 2.0*scale;`) both work.
- An **unresolved target is a hard error** naming the original source path
  (`defparam target(s) did not resolve to any parameter: u1.typo`).

## Run

```
python3 verify_defparam.py
```

Checks (4, ALL PASS, exact op-point conductances): a basic instance
override (1k → 2k → 0.5 mA); a two-level target plus a multi-assignment
defparam overriding an instance `#()` (1.75 mA total); an
expression-valued override referencing a parent parameter (6k → 1/6 mA);
and the unresolved-target compile error.

## Note

`defparam` targeting a *same-module* parameter in a module that has no
instantiation at all is not rewritten (the elaboration pass only runs when
the file contains instantiations) — use the parameter's declared default
there. The hierarchical instance-override use case, which always involves
instantiation, is fully supported.
