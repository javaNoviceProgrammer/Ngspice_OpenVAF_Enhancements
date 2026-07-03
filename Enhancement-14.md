# Enhancement-14 — Verilog-A array literals / aggregates (version11)

This document describes the source-code changes made to **OpenVAF-r** in the
`version11/` directory to implement **array literals and aggregate operations**
on top of Enhancement-13. Before this, arrays existed only as Enhancement-3/4
"bus-style" declarations (`real [0:n] x;`) accessible one element at a time by a
**constant** index (`x[0]`); a whole array could not be assigned, an array could
not be a parameter, and a non-constant index was rejected.

Enhancement-14 adds three capabilities (all verified end-to-end through
ngspice — see `array_examples/`):

- **A. Whole-array aggregate assignment** — `c = '{v0, v1, ...};` (and the
  brace-only `{...}` form) and array-to-array copy `c = d;`.
- **B. Array-valued parameters** — `parameter real [msb:lsb] c = '{...};`, with
  a per-element default and per-element SPICE override (`c[0]`, `c[1]`, …).
- **C. Dynamic (non-constant) indexing** — `c[i]` reads and writes with a
  runtime index, lowered to a select over the array's element variables.

All work is in `version11/` only; verification uses `version11/ngspice-46`'s own
binary and `version11/OpenVAF-master`'s own `openvaf-r`. **No OSDI ABI change and
no ngspice change were needed** — array parameters surface as ordinary scalar
OSDI parameters (one per element), and everything else lowers to ordinary MIR.

## 0. Starting point and representation

Array variables/nets are already **expanded into independent scalar entries** at
item-tree time: `real [0:2] c;` registers a `BusDecl` in `Module::var_arrays`
and declares three scalar variables named `c[0]`, `c[1]`, `c[2]`
(`hir_def::item_tree::lower::lower_var`). A constant bit-select `c[k]` resolves,
via the synthesized path `c[k]`, to the corresponding scalar `VarId`
(`hir_ty::inference::infere_bit_select`). Enhancement-14 builds entirely on this
expansion: an aggregate operation is just a set of per-element scalar
operations, and a dynamic index is a runtime select over the same elements.

A pre-existing **infinite-loop bug** was found and fixed while doing this:
`Type::base_type` (`hir_def/src/types.rs`) looped `while let Type::Array{..} = self`
(testing the unchanging `self` instead of the loop cursor `curr`), so any
`base_type()` call on an array type hung the compiler. It is reached through
`is_assignable_to`/`is_convertible_to`, so e.g. assigning an array literal to a
scalar (`real x; x = '{...};`) hung instead of reporting a type error. Now fixed
(`= curr`), and such mismatches report a clean diagnostic.

## A. Whole-array aggregate assignment

`Expr::Array` (an `'{...}` literal) previously reached `hir_lower`'s `lower_array`,
an `unimplemented!("arrays")` — but only after the front-end had already rejected
the bare array destination with a "requires a bit-select" error, so the todo was
in practice unreachable. Enhancement-14 handles the whole statement in inference
and desugars it to per-element assignments.

- **`hir_ty::inference`** — `try_infere_array_assignment` runs before ordinary
  assignment inference. If the destination is a bare reference to a `var_array`,
  it resolves the destination element `VarId`s (declaration order, msb→lsb, the
  order a literal fills) and type-checks the right-hand side:
  - an array literal `'{...}` (each element inferred and cast to the element
    type; length checked against the destination),
  - or a bare reference to another array variable (`c = d`, element types and
    lengths checked).

  The decomposition is recorded in `InferenceResult::array_assignments` as an
  `ArrayAssign::{Literal, Copy}`. Length/element-type mismatches reuse the
  existing `TypeMismatch` diagnostic (rendered as e.g. *"expected real[0:3] value
  but found real[0:2] value"*), so no new diagnostic wiring was needed.
- **`hir`** — a new elaborated `Stmt::ArrayAssignment { assigns: Vec<ArrayAssignElem> }`
  is produced by `get_stmt` when a statement has an `array_assignments` entry;
  each element is `ArrayAssignElem::{Val { dst, val }, Copy { dst, src }}`.
- **`hir_lower::stmt`** — lowers `Stmt::ArrayAssignment` as its per-element scalar
  `def_place`s (a `lower_expr` for a literal element, a `read_variable` for a
  copy source). Per-element int→real casts are applied by the usual
  `needs_cast` path.

## B. Array-valued parameters

- **`parser`** (`grammar/items.rs::parameter_decl`) — accepts an optional
  `[msb:lsb]` width clause after the parameter type, mirroring `var_decl`. The
  AST grammar (`veriloga.ungram`, generated `nodes.rs`) gains
  `ParamDecl::width()`.
- **`hir_def::item_tree`** — `Param` gains `array_index: Option<u32>` and `Module`
  gains `param_arrays: Vec<BusDecl>`. `lower_param` (at module scope) expands an
  array parameter into one scalar `Param` per element, named `c[lo]`..`c[hi]`,
  each tagged with its declaration-order position, and registers a `param_arrays`
  `BusDecl` so `c[i]` bit-selects resolve to the element parameters. (A width
  clause in an unsupported scope, or a non-constant width, degrades to a scalar
  parameter, as for array variables.)
- **`hir_def::body`** — the parameter default body query gives each element
  parameter *its own* default: the `array_index`-th element of the shared
  `'{...}` literal (rather than the whole literal).
- **`hir_ty::inference`** — `find_param_array` (analogous to `find_var_array`)
  lets `infere_bit_select` resolve `c[k]` to the element `ParamId` (typed as
  `Ty::Param`), and lets the bare-reference guard reject an un-indexed array
  parameter.

Because each element is an ordinary parameter, it becomes an ordinary OSDI
parameter automatically. ngspice reads its default and **overrides it
per-element** by name — `.model m array_demo(w[2]=0.9)` sets only `w[2]`, leaving
the others at their literal defaults. (Confirmed: ngspice accepts the bracketed
parameter name.)

## C. Dynamic (non-constant) indexing

A non-constant index can't resolve to one element, so it lowers to a runtime
select over the elements. This applies to array **variables** (mutable state);
array parameters are constant tables read by a constant index (a parameter table
is indexed dynamically by first copying it into an array variable — see
`array_examples/array_demo.va`).

- **`hir_ty::inference`** — `infere_bit_select`, on a non-constant index of a
  variable array, records `dynamic_index_refs[expr] = DynArrayIndex { elems,
  index, lsb }` (element `VarId`s in ascending bit order) and types the read as
  the element type. A dynamic *write* `c[i] = v` is caught by
  `try_infere_dynamic_index_assignment` and recorded in
  `dynamic_index_assignments`. A **literal** index that failed to fold (e.g. an
  oversized integer) is *not* treated as dynamic — it stays a "non-constant
  bit-select index" diagnostic (`is_literal_index` guard), preserving existing
  behaviour and the `huge_int_literal` regression test.
- **`hir`** — exposes `dynamic_index(expr)` for reads and emits a new
  `Stmt::DynArrayAssignment { elems, index, lsb, value }` for writes.
- **`hir_lower`** — a dynamic **read** (`lower_dynamic_index_read`, intercepted at
  the top of `lower_expr`) builds `res = elems[0]; res = (i == lsb+k) ? elems[k]
  : res` for each `k`. A dynamic **write** updates every element conditionally:
  `elems[k] = (i == lsb+k) ? v : elems[k]`. Both use `Opcode::Ieq` + `make_select`.

## Verification

- `array_examples/verify_array.py` — array-parameter defaults, full and partial
  per-element override, aggregate assignment, array copy, and dynamic read/write
  all match their closed-form gains through ngspice (`ALL PASS`).
- The `hir_def`/`hir_ty`/`hir`/`hir_lower`/`parser`/`syntax` unit-test suites pass
  with no regressions (including the `huge_int_literal` bit-select regression
  test). The pre-existing stale `sim_back` DAE/topology snapshot failures are
  unchanged (identical 9-pass/15-fail before and after Enhancement-14) and are
  unrelated to arrays.
- Every prior `*_examples/` folder still compiles and simulates with unchanged
  results.

## Known limitations

- Dynamic indexing of an array **parameter** is not supported directly (copy the
  parameter into an array variable and index that). A non-constant index on a
  parameter array reports the ordinary "non-constant bit-select index" error.
- Arrays remain one-dimensional (matching the existing bus/array-variable
  model); nested `'{{...},{...}}` aggregates are not supported.
- The array-literal fill order follows the declared `[msb:lsb]` direction.
