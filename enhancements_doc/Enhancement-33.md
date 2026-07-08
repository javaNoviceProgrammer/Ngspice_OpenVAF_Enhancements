# Enhancement-33 — array `case` + array-literal function arguments

This document describes the changes made to **OpenVAF-r** in the `version11/`
directory to retire the compiler's **last `todo!()` hard-panic stubs** and fix the
array-expression bugs found underneath them. Purely front-end (`hir_ty` +
`hir_lower`); no OSDI/ngspice change.

## The bugs

A deep-dive TODO sweep (the one that produced Enhancement-32) left two `todo!()`
stubs in `hir_lower`. Probing their reachability uncovered four related defects:

1. **`case` over an array crashed the compiler.** Type inference happily accepted an
   array-typed discriminant (demanding array-typed items), but lowering hit
   `Type::Array { .. } => todo!()` in `lower_case`:

   ```
   case ('{1.0, 2.0})
     '{1.0, 2.0}: g = 1e-3;    // -> "not yet implemented" panic
   ```

2. **Array-literal function arguments silently bound nothing.** A whole-array
   function argument (Enhancement-18) only handled bare array-*variable*
   references; a literal compiled cleanly but left every element 0:

   ```
   g = sum2('{1.0, 2.0});      // returned 0 instead of 3 — silent wrong answer
   ```

3. **Whole-array variables were typed `real` regardless of their element type.**
   `infere_array_arg` hardcoded `Type::Real`, so an *integer*-array `case`
   discriminant compared its i32 elements with `feq` — a second panic
   (`invalid int operation feq` in const-eval).

4. **Array literals were silently accepted as array *output* arguments** (the
   Enhancement-20 writeback just skipped), while scalar output arguments have
   always properly required a variable.

## The fixes

- **Element-wise array `case`** (`hir_lower/src/stmt.rs`): the discriminant and
  each case item are lowered to their element `Value`s and the per-element
  equalities (`feq`/`ieq`/`beq`/`seq` by element type) are AND-combined into the
  single branch condition — an arm matches iff **all** elements are equal. The
  scalar path is unchanged (it is just the one-element case). Works for array
  literals and whole-array variables, real and integer, in both positions;
  mismatched lengths stay a clean type error.

- **Shared array-expression helpers**: the laplace-specific helpers were the
  general mechanism all along, so they are renamed and reused —
  `lower_laplace_array_arg` → `lower_array_elems` (hir_lower) and
  `infere_laplace_array_arg` → `infere_array_arg` (hir_ty). The `case` inference
  arm now runs discriminant/items through `infere_array_arg`, which also registers
  whole-array variable references (previously `case (x)` on an array variable was
  rejected with "requires a bit-select").

- **Array-literal function arguments** (`hir_lower/src/expr.rs`,
  `lower_user_fun_impl`): the input-binding now uses `lower_array_elems`, which
  handles literals (each element lowered) and variable references (each element
  read) identically — `sum2('{1.0, 2.0})` returns 3.

- **True element types** (`hir_ty/src/inference.rs`, `infere_array_arg`): a
  whole-array variable is typed from its actual element variables instead of
  hardcoded `real`, so integer arrays compare with `ieq` and mixed-type
  discriminant/item combinations are diagnosed instead of miscompiled.

- **Array output arguments require a variable** (`hir_ty/src/inference.rs`): an
  array literal passed to an `output`/`inout` array formal is now rejected with
  the same "expected … variable reference" diagnostic scalars get, instead of
  silently skipping the writeback.

- **The stubs are retired**: `lower_case`'s `todo!()` is replaced by the working
  array path, and `lower_array`'s `todo!("arrays")` becomes a documented
  `unreachable!` — every context that accepts an array value consumes its
  elements directly (aggregate assignment, laplace/zi, `$table_model`, function
  arguments, `case`), and inference rejects arrays everywhere else, so no array
  expression can reach the generic scalar lowering path.

## Verification — `arraycase_examples/`

`arraycase_demo.va` classifies the input voltage into a 2-bit **integer** state
vector and selects the conductance with one element-wise array `case`
(`case (st) '{0,0}: … '{1,0}: … '{1,1}: …`), scaled by a helper summing an
array-literal argument (`sum2('{0.25, 0.75}) == 1.0`). `verify_arraycase.py`
(ALL PASS) checks, end-to-end through version11's own `openvaf-r` + `ngspice`:

1. it **compiles** (array `case` used to panic the compiler);
2. all three case regions select the correct conductance in a DC sweep — which
   simultaneously proves the literal function argument reads 1.0, not 0;
3. a real-array `case` (literal discriminant vs literal item) compiles and matches;
4. an array literal passed to an array **output** argument is rejected with a
   proper type error.

Regressions: every array-consuming feature re-verified — `funcarray` (E-18),
`arrayout` (E-20), `arrayret` (E-23), `array`/`mdarray` (E-14/15),
`cubic_table`/`table_model` (E-16/22), `complexpole` (E-31, exercises the renamed
`lower_array_elems` via laplace) — **ALL PASS**, plus `zi_lpf` and a scalar `case`
model behave unchanged.
