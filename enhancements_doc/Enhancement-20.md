# Enhancement-20 — array output/inout arguments to analog functions

This document describes the source-code change made to **OpenVAF-r** in the
`version11/` directory to support **`output`** and **`inout`** array arguments to
`analog function`s, completing Enhancement-18's array-argument support (which was
**input-only**: a whole array could be passed *into* a function, but a function
could not write one back).

Before this, an array `output`/`inout` argument **compiled but silently did
nothing** on return — the function computed into its element variables, but they
were never copied back to the caller's array (a correctness gap). Now the
writeback happens, so `fill(r)` and `scale_in_place(r)` actually update `r`.
Verified end-to-end through ngspice — see `examples/arrayout_examples/`.

## The change

Enhancement-18 already lowered a whole-array argument by binding the callee's
element variables (`v[i]`) from the caller's array elements at function entry
(input semantics), and its inference (`pre_resolve_array_call_arg`) already
resolved the caller's array to its element `VarId`s (`array_var_refs`) for *any*
array argument, input or output. The only missing piece was the **exit
writeback**, which the Enhancement-18 writeback loop explicitly skipped for array
arguments.

`lower_user_fun_impl` (`hir_lower/src/expr.rs`) now, for an **output** (or
**inout**) array argument, copies each of the function's element variables back to
the corresponding caller array element after the body has run:

```text
for each element i:  caller_array[i] = read(callee_element_var[i])
```

reusing the same `FunctionArg::array_elems` (callee element `VarId`s, via
`hir_def::function_array_arg_vars`) and `Body::array_var_ref` (caller element
variables) machinery introduced in Enhancement-18. Because the callee body is
lowered inline, these are ordinary variable defs in the same MIR. `inout`
arguments get both the entry bind (from Enhancement-18) and this exit writeback;
`input` arguments are unaffected.

## Verification

- `examples/arrayout_examples/verify_arrayout.py` — `make_taps` fills a geometric tap array
  via an **output** array argument, `normalize` scales it in place via an
  **inout** array argument, and the gain is the sum of the normalized taps. That
  sum is 1 for any `ratio` (swept, overridden per `.model`), so `V(out) = V(in)`
  — which holds only if both writebacks reach the caller's array. `ALL PASS`.
- Ad-hoc: a pure `output` array argument (`fill(r)` sets `r = {3,4}`) and an
  `inout` array argument (`scale2(r)` doubles `r` in place) both produce the
  expected caller-side values; Enhancement-18 `input` array arguments are
  unchanged (`funcarray_examples` still passes).
- The `hir_lower`/`hir_ty`/`hir` unit-test suites pass with no regressions; every
  prior example folder still compiles and simulates unchanged.

## Known limitations

- The array actual passed to an `output`/`inout` argument must be a writable array
  **variable** (a bare array reference). Passing a non-writable array expression
  is a silent no-op on writeback rather than a diagnosed error.
- Array **return values** (a function whose return type is an array) remain
  unsupported; use an `output` argument instead.
