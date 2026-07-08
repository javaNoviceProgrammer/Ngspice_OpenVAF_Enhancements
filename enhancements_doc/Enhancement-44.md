# Enhancement-44 — paramset hierarchical system parameters

This document describes the changes made to **OpenVAF-r** in the `version11/`
directory to support **hierarchical system parameters in paramsets**
(`.$mfactor = 8;`, LRM 6.4 — the canonical "quad device" idiom). No
OSDI/ngspice change.

## Baseline (probed first, all correct)

The six hierarchical system parameters (`$mfactor`, `$xposition`,
`$yposition`, `$angle`, `$hflip`, `$vflip`) were already fully working at the
instance level:

- readable in expressions with exact LRM defaults (1 / 0 / 0 / 0 / 1 / 1);
- settable per-instance in ngspice — `m=` for `$mfactor` (the OSDI layer's
  standard alias) and `_xposition=` … for the rest (ngspice rewrites the `$`
  prefix to `_`, since `$` starts a netlist comment);
- `$mfactor` semantics exact: flow contributions ×m, potential contributions
  invariant, noise PSD ×m, correct across E-5-flattened sub-instances.

The gap: a paramset could not set them — `.$mfactor = 8;` was a parse error
("unexpected token system function identifier"), yet per LRM 6.4 paramsets may
specify hierarchical system parameters alongside parameter bindings.

## Semantics

The paramset value **composes** with the instance-level value, per the LRM's
hierarchy rules:

- `$mfactor`, `$hflip`, `$vflip` — **multiplicative** (multiplicities and
  flips multiply down the hierarchy): `m=3` on a `.$mfactor = 8` paramset
  gives an effective 24;
- `$xposition`, `$yposition`, `$angle` — **additive** (offsets accumulate).

The composed value must be seen by *every* consumer: explicit `$mfactor` reads
in the body, the DAE builder's automatic flow scaling, its `sqrt(mfactor)`
noise-factor scaling, and all derivative code. Override expressions are
`paramset_constant_expression`s and may reference the paramset's own card
parameters (`.$mfactor = nf;`), including their model-card overrides.

## Implementation

- **`parser/grammar/items.rs`** — `paramset_override` accepts a SYSFUN token
  as the overridden name, wrapped in the same `NAME_REF` node (plus a
  `NameRef::sysfun_token()` accessor in `syntax`).
- **`hir_def/item_tree/lower.rs`** (`lower_paramset`) — each HSP override
  becomes a hidden **real localparam named `$paramset$<name>`** in the E-21
  twin module, with the override expression as its `override_expr` (the
  ordinary E-21 localparam-with-override machinery evaluates it in twin scope,
  so card-parameter references and model-card overrides just work). The
  `$`-spelling collides with no user identifier and deliberately differs from
  the OSDI built-in `$mfactor` instance parameter — so ngspice's `m=` alias
  keeps pointing at the *instance* value. Unknown system functions
  (`.$vt = 1;`) get a named diagnostic
  (`ItemTreeDiagnostic::InvalidParamsetSysParam`). The synthetic param's
  `ast_id` is a placeholder (E-23 `from_erased` trick); the override branch of
  `param_body_with_sourcemap` was reordered to not dereference the
  `ast::Param` node it doesn't have.
- **`hir_lower/state.rs`** — new `HirInterner::insert_paramset_sys_fun_overrides`,
  modeled on the E-7 `insert_var_init` use-rewrite: for each override, read
  the hidden localparam (`ParamKind::Param`), build `fmul`/`fadd` with the
  `ParamKind::ParamSysFun` value, and rewrite every pre-existing use of the
  system parameter with the composed value.
- **`sim_back/lib.rs`** — the pass runs **after `DaeSystem::new`** (so the
  automatic mfactor flow/noise scaling and the derivative code exist and get
  rewritten) and before the post-derivative optimization; the twin's hidden
  localparams are recognized by their `$paramset$` name prefix. One
  supporting fix: the pass creates new MIR values, so `output_values` is
  re-grown — `BitSet::contains` in the init-cache dead-code pass indexes by
  value and paniced otherwise.

## What now works (`paramsethsp_examples/`, all exact)

| case | result |
|---|---|
| `paramset quad rbase; .r = 2e3; .$mfactor = 8;` | 250 Ω effective (−4 mA at 1 V) |
| quad + netlist `m=3` | effective 24 → −12 mA |
| all six HSPs in one paramset, read back | 8254.89 composed exactly |
| + instance `m=3 _xposition=5 _hflip=-1` | 24755.09 (× m, + positions, × flips) |
| `.$mfactor = nf` (card param) | −5 mA at default nf=5, −2 mA with `nf=2` |
| noise through paramset multiplicity | onoise 5e-4 = netlist `m=4` exactly |
| `.$vt = 1;` | "'$vt' is not a hierarchical system parameter" |

`verify_paramsethsp.py`: 8/8 PASS. Regression: all 40 example verify suites
ALL PASS; `sim_back`/`hir_def`/`hir_lower`/`parser`/`syntax` crate tests pass.

## Notes

- The `sim_back` MIR snapshot files (`test_data/dae`/`topology`/`init`) were
  stale from earlier enhancements (the suite hadn't been run since ~E-36's DAE
  builder changes) and failed identically on the committed pre-E-44 sources;
  they were refreshed with `UPDATE_EXPECT=1` against the current (verified
  bit-identical at E-42) behavior.
- Paramsets *selecting* on hierarchical system parameters (LRM's
  restriction-checking use) remain out of scope; only value specification is
  implemented.
