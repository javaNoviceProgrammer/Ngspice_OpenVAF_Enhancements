# Enhancement-18 — array declaration syntax + arrays in analog functions (version11)

This document describes two related source-code changes made to **OpenVAF-r** in
the `version11/` directory:

1. **Standard array declaration syntax** — the LRM *name-then-range* form
   `real x[0:n];` (and multi-dimensional `real m[0:1][0:2];`), complementing the
   existing *range-then-name* form `real [0:n] x;`.
2. **Array support in `analog function`s** — array **local variables** and whole
   **array arguments**, previously rejected with *"array-variable declarations
   are only supported at module body scope"*.

Both are verified end-to-end through ngspice — see `funcarray_examples/`. All work
is in `version11/`; **no OSDI ABI change and no ngspice change were needed**.

## Part 1 — `real x[0:n]` declaration syntax

Verilog-AMS declares unpacked arrays as `real coeffs[0:4];` (dimensions *after*
the name), whereas OpenVAF previously only accepted `real [0:4] coeffs;`
(dimensions *before* the name). Enhancement-18 accepts both, per-variable.

- **Parser** (`grammar/items.rs::var`) — after a variable name, parses zero or
  more `[msb:lsb]` clauses (`x[0:n]`, `m[0:1][0:2]`). **AST** (`Var::widths()`,
  ungram) exposes them.
- **`item_tree::lower_var`** — each variable's dimensions are its own name-then-range
  `widths` if present, else the shared declaration-level range-then-name widths.
  So `real g, w[0:1], k;` declares a scalar, a 1-D array, and a scalar. Everything
  downstream (the Enhancement-14/15 element expansion) is unchanged.

## Part 2 — arrays in analog functions

Array variables were expanded into scalar element variables (`x[0]`, `x[1]`, …)
only at *module body* scope. Enhancement-18 extends this to `analog function`
bodies and adds whole-array argument passing.

- **Function-scope array locals** — `item_tree::Function` gains a `var_arrays`
  list; `lower_fun` passes it to `lower_var` (previously `None`), so array locals
  and array-typed argument declarations expand into element variables inside the
  function. `hir_ty::find_var_array` now also resolves arrays for a
  `DefWithBodyId::FunctionId` owner, so `x[i]` bit-selects (constant *and* dynamic)
  work in a function body exactly as at module scope.
- **Array-typed arguments** — `function_data_query` types an argument whose name
  matches a function `var_array` as `Type::Array{elem, len}` (its declaration
  expanded to element variables, so it has no single scalar declaration).
- **Whole-array call binding** — at a call `f(c, ...)`, `infere_user_fun_call`
  pre-resolves a bare array actual passed to an array formal into its element
  `VarId`s (recorded in `array_var_refs`, matching the laplace-argument
  mechanism), and `infere_expr` returns the array type for such a pre-resolved
  reference instead of the "requires a bit-select" error. In lowering,
  `lower_user_fun_impl` binds the callee's element variables (resolved via
  `hir_def::function_array_arg_vars`, which resolves the `v[i]` names in the
  function's body scope) from the caller's array elements — pass-by-value of the
  elements. Because the callee body is lowered inline as ordinary MIR, the
  Jacobian flows through the function automatically.

Array arguments are **input** (element pass-by-value); array `output` writeback and
array return values are not supported.

## Verification

- `funcarray_examples/verify_funcarray.py` — a polynomial stage
  `V(out) = 0.5·V(in) + 0.3·V(in)²` evaluated inside an array-argument function
  `polyeval(x, a)` (Horner's rule, indexing the array argument with a loop
  variable), with `coeffs` declared `real coeffs[0:3];` and passed by name:
  - **DC** — `V(out)` matches the closed-form polynomial (~1e-16);
  - **AC** — the small-signal gain matches `poly'(bias) = 0.5 + 0.6·bias` (~1e-16),
    i.e. the derivative flows through the array-argument function into the Jacobian.
- Ad-hoc checks: `real x[0:n]`/`real m[0:1][0:2]`/mixed `real g, w[0:1], k;`
  declarations simulate correctly; array locals with dynamic indexing inside a
  function work; a `dot(c, w)` array-argument function returns the expected value.
- The `hir_def`/`hir_ty`/`hir`/`hir_lower`/`parser`/`syntax` unit-test suites pass
  with no regressions; every prior example folder still compiles and simulates.

## Known limitations / future work

- Array **output** arguments (writing a whole array back to the caller) and array
  **return values** are not supported — array arguments are input-only.
- A width clause inside a *nested* `begin..end` block (rather than at the function
  or module top level) still degrades to a scalar with a diagnostic.
