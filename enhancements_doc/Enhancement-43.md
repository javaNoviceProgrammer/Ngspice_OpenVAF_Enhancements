# Enhancement-43 — variable initializers, completed (version11)

This document describes the changes made to **OpenVAF-r** in the `version11/`
directory to complete **declaration initializers** (`real x = 2.5;`). All
changes are in `hir_def`; no OSDI/ngspice change.

## What already worked (verified, kept as regression checks)

Scalar module-level initializers (`real`/`integer`/`string`), initializers
that are constant expressions over **parameters** (`real y = 2.0*p + 1.0;`,
re-evaluated against model-card overrides), named-block locals, multiple
declarators, implicit real→integer rounding, and — the semantic core — LRM
**init-once** behavior: each live unwritten variable read becomes a
`ParamKind::HiddenState` input that `hir_lower/state.rs` seeds from the
variable's initializer body gated on `IsInitialStep`, so event-updated state
*starts* at the initializer and is never re-initialized per evaluation
(`integer cnt = 10;` + `@(cross) cnt = cnt + 1;` counts 10, 11, …).
Initializers referencing other *variables* are correctly rejected
("constant expressions must not contain variable references").

## The three defects

1. **Array declaration initializers were rejected.** `real x[0:2] = '{1.0,
   2.0, 4.0};` — an array variable expands into per-element scalar variables
   (E-14), and *each* element's body picked up the **whole** `'{...}`
   aggregate, so the type check failed "expected real value but found
   real[0:3] value" once per element (the mysterious triplicated diagnostic).

2. **Untyped analog-function arguments crashed the compiler.** In
   `analog function real f; input v; … endfunction` with no `real v;`
   declaration, `FunctionArg::ty` returned `Type::Err`
   (`declarations.first().map_or(Type::Err, …)`), which flowed into inference
   and hit `unreachable!("unknown cast found Real -> Err")`
   (`hir_lower/ctx.rs`) at the first cast involving the argument. (This
   masqueraded as a "function-local initializer crash" during probing — the
   initializer was innocent.)

3. **Wrong-arity initializers crashed the compiler — variables *and*
   parameters.** `real x[0:2] = '{1.0, 2.0};` (or the array-parameter
   equivalent, a *pre-existing* E-14 latent bug) produced `Expr::Missing` for
   the uncovered elements with no diagnostic, and lowering died with
   "invalid HIR: Missing".

## The fix (hir_def only)

- `item_tree.rs` / `item_tree/lower.rs`: `Var` gains `array_index:
  Option<u32>` — each expanded element records its flat declaration-order
  (row-major) position, exactly mirroring `Param::array_index` (E-14/15).
- `body.rs`: an element variable's body takes the matching **leaf** of the
  shared `'{...}` literal (`flatten` + `nth(pos)`, the same split the param
  path uses). N-D nesting comes free — the flatten is row-major, matching the
  element expansion order; integer leaves in a real array get the normal
  implicit cast; leaves may be constant expressions over parameters and are
  re-evaluated on overrides. Everything downstream (hidden-state seeding,
  init-once gating, function-local expansion) works unchanged because each
  element is just a scalar variable with its own initializer body.
- `item_tree.rs` (`FunctionArg::ty`): an argument with no type declaration
  defaults to **`real`**, matching the untyped-return default
  (`analog function f;` is a real function per the LRM).
- `item_tree/lower.rs`: both array-expansion sites (variables and parameters)
  count the literal's leaves against the declared element count and emit a
  new named diagnostic — `array initializer for 'x' has N element(s) but the
  array has M` — covering too-few, too-many, and scalar-on-array forms.

## What now works (`varinit_examples/`, all exact)

| case | result |
|---|---|
| `real v1[0:2] = '{1.0, 2.0, 4.0};` + `integer iv[0:1] = '{8, 16};` | elements read exactly |
| `real m[0:1][0:2] = '{'{…},'{…}};` (2-D), 3-D with integer leaves | row-major leaves, casts applied |
| `real pd[0:1] = '{s, 3*s};` | leaves track `s` model-card override |
| `real acc[0:1] = '{100.0, 0.0};` + `@(cross)` update | starts at 100, init-once |
| function-local `real w[0:2] = '{…}` + scalar init + **untyped `input v`** | evaluates exactly (was ICE) |
| `'{1.0, 2.0}` on `[0:2]` (var or param), `'{…×4}`, scalar-on-array | clean named diagnostic (was ICE) |

`verify_varinit.py`: 12/12 PASS. Regression: all 39 example verify suites ALL
PASS; `hir_def`/`hir_ty`/`hir_lower`/`hir`/`syntax`/`parser` crate tests pass.

## Notes

- The stale `lower_var` comment claiming array initializers are "silently
  ignored" (Enhancement-4 era) was removed — they are now real.
- `parameter real [0:2] c = '{1.0, 2.0};` crashing was pre-existing (E-14);
  the new arity diagnostic covers it through the shared code path.
