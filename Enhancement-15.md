# Enhancement-15 — Verilog-A multi-dimensional arrays (version11)

This document describes the source-code changes made to **OpenVAF-r** in the
`version11/` directory to generalise the 1-D array support of Enhancement-14 to
**multi-dimensional arrays** (`real [0:1][0:2] m; ... m[i][j]`). It covers array
variables and array-valued parameters, constant and dynamic (runtime) indexing,
and nested aggregate literals — verified end-to-end through ngspice (see
`mdarray_examples/`).

All work is in `version11/`; verification uses `version11/ngspice-46`'s own
binary and `version11/OpenVAF-master`'s own `openvaf-r`. **No OSDI ABI change and
no ngspice change were needed** — a multi-dim array parameter surfaces as one
ordinary scalar OSDI parameter per element (named `w[i][j]`), which ngspice
overrides individually, and everything else lowers to ordinary MIR.

## 0. Representation

The design keeps every array (net, variable, parameter) expanded into
independent **scalar elements**, exactly as the 1-D bus/array machinery already
did; a multi-dim array simply has more elements, named by their full index tuple
(`m[i][j]`). Two representation changes carry the extra dimensions:

- **`Expr::BitSelect`** (`hir_def`) changes `index: ExprId` → `indices:
  Vec<ExprId>`. A single bit-select node now carries every `[..]` clause of an
  access (`m[i][j]` → `indices = [i, j]`), since an array's base is always its
  name. 1-D is the common case (`indices.len() == 1`).
- **`BusDecl`** (`hir_def::item_tree`) gains `dims: Vec<(i32, i32)>` (one
  `(msb, lsb)` per dimension, outermost first). The existing `msb`/`lsb` fields
  are kept (`== dims[0]`) so all 1-D net/array code is untouched. New helpers:
  `ndim`, `elem_count`, `contains`, `elem_name` (synthesizes `m[i][j]`), and
  `index_tuples` (every index tuple in declaration order — each dimension
  `msb`→`lsb`, outermost slowest, the order a nested literal fills).

## 1. Parsing

- **`grammar/expressions.rs`** — the postfix `[..]` after an identifier now
  *loops*, collecting `m[i][j]...` into one `BIT_SELECT_EXPR` with several index
  children.
- **`grammar/items.rs`** — `var_decl` and `parameter_decl` loop the `[msb:lsb]`
  width clause, so a declaration can carry several dimensions.
- **AST** (`veriloga.ungram`, generated `nodes.rs`) — `BitSelectExpr::indices()`,
  `VarDecl::widths()`, `ParamDecl::widths()` (the plural `AstChildren` accessors).
- Consumers of the old single accessors are updated: `hir_def::body::lower`
  (collects all indices), `body::pretty`, and `hir::elaborate`'s
  `generate for` genvar bit-select folding (folds every index sub-expression).

## 2. Declaration & element expansion

`fold_width_ranges` folds all width clauses into `dims`. `lower_var` / `lower_param`
build one `BusDecl` with those `dims` and declare one scalar element per
`index_tuples()` entry, named via `elem_name` (`x[i]` for 1-D — byte-identical to
before — or `x[i][j]` for multi-dim). An array parameter's elements each carry an
`array_index` = their flat declaration-order position.

## 3. Constant indexing

`infere_bit_select` (`hir_ty`) is rewritten for N indices: it checks the index
count against `ndim` (new `WrongArrayDimensions` diagnostic), constant-folds every
index, range-checks the tuple (`contains`), and resolves the synthesized
`elem_name` path to the element `VarId`/`ParamId`/`NodeId`. A vectored net still
requires exactly one constant index.

## 4. Dynamic (runtime) indexing

When any index is non-constant (a genuine runtime value, not an unfoldable
literal — the `is_literal_index` guard is preserved), a **variable** array access
is recorded for a runtime element select:

- `DynArrayIndex` (`hir_ty`) now stores the flat element `VarId`s (declaration
  order), the per-dimension `dims`, and one index expression per dimension.
  `infere_dynamic_bit_select` builds it for reads; `try_infere_dynamic_index_assignment`
  for writes (`m[i][j] = v`). Mixed constant/dynamic indices (`m[0][j]`) are
  supported.
- **`hir_lower`** — `lower_flat_array_index` computes the runtime flat position
  `Σ_k pos_k·stride_k` (`pos_k = idx-msb` ascending / `msb-idx` descending;
  `stride_k` = product of later dimension sizes), matching `index_tuples`
  ordering. A read selects `elems[flat]`; a write conditionally updates every
  element (`elems[k] = (flat == k) ? v : elems[k]`). Both reuse `make_select`.

Array *parameters* are constant tables and stay constant-indexed (a non-constant
index on a parameter array is the ordinary "non-constant bit-select index"
error); copy a parameter into a variable array to index it dynamically.

## 5. Nested aggregate literals

- **Assignment** — `try_infere_array_assignment` flattens the RHS literal
  (`flatten_array_literal`: `'{'{a,b},'{c,d}}` → `[a,b,c,d]`, row-major) and
  zips the leaves against the destination's flat element list. Length/element-type
  mismatches reuse the existing `TypeMismatch` diagnostic. Array-to-array copy
  (`m = d`) and 1-D flat literals are unchanged special cases of the same code.
- **Parameter defaults** — the parameter body query flattens the (possibly
  nested) default literal at the AST level and gives each element parameter the
  leaf at its `array_index`.

## Verification

- `mdarray_examples/verify_mdarray.py` — 2-D array parameter defaults, per-element
  2-D override (`w[1][1]=0.9`), nested-literal aggregate assignment, and dynamic
  2-D read/write all match their closed-form gains through ngspice (`ALL PASS`).
- The `hir_def`/`hir_ty`/`hir`/`hir_lower`/`parser`/`syntax` unit-test suites pass
  with no regressions. Every prior `*_examples/` folder still compiles and
  simulates unchanged — including the 1-D `array_examples` (Enhancement-14),
  vectored-net `bus_examples`, `generate` genvar bit-select folding, and the
  `laplace` array-coefficient forms. The pre-existing stale `sim_back` snapshot
  failures (9 pass / 15 fail) are unchanged and unrelated.

## Known limitations

- Aggregate-literal shape is validated by total element **count**, not per-level
  shape, so a ragged literal with the right leaf count is accepted.
- A whole multi-dim array is not itself a first-class value (no slicing, no
  passing a whole array to a function) — access is always down to a scalar
  element, as for 1-D arrays.
