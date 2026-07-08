# Enhancement-25 — `$simparam$str(name)` support

This document describes the changes made to **OpenVAF-r** *and* **ngspice-46** in
the `version11/` directory to make **`$simparam$str(name)`** work. It returns a
*string* simulator parameter (the string counterpart of the numeric
`$simparam`). Previously it was completely unusable, due to three independent
defects — two in OpenVAF, one in ngspice.

## The three defects

1. **Wrong return type (OpenVAF, `hir_ty/src/builtin.rs`).** The builtin signature
   declared `SIMPARAM_STR(...) -> Real`, so any use in a string context (assigning
   to a `string` variable, comparing to a string literal, `%s` in `$strobe`) was a
   `type mismatch: expected string value but found real value`. Fixed to
   `-> String`.

2. **Bugged runtime lookup (OpenVAF, `osdi/stdlib.c`).** `simparam_str` iterated the
   *numeric* name list (`params->names[i]`) and, on a match, returned the *name*
   (`params->names_str[i]`) instead of the *value* — and, because the string list
   is shorter than the numeric one, read past the end of `names_str`. Fixed to walk
   the NULL-terminated `names_str` list and return `vals_str[i]`.

3. **No string parameters exposed (ngspice, `src/osdi/osdiload.c`).**
   `get_simparams` set `sim_params_str = {NULL}` and `vals_str = NULL`, so even a
   correct lookup had nothing to find. Now it exposes two string parameters and
   fills their values each call.

## What ngspice exposes

- **`"analysis_name"`** — `"dc"` / `"ac"` / `"tran"` / `"noise"`, derived from
  `CKTmode` with the same convention as `analysis()` (noise → ac → tran → dc).
- **`"simulator"`** — the constant `"ngspice"`.

An unknown name raises a fatal "unknown $simparam_str" (matching the numeric
`$simparam` with no default).

## Files changed

- **OpenVAF** `hir_ty/src/builtin.rs` — `SIMPARAM_STR` return type `Real → String`.
- **OpenVAF** `osdi/stdlib.c` — `simparam_str` walks `names_str` and returns
  `vals_str`.
- **ngspice** `src/osdi/osdiload.c` — `get_simparams` exposes `"analysis_name"` and
  `"simulator"` (the second enhancement to also touch the ngspice source, after
  Enhancement-24). No OSDI ABI change.

The OpenVAF lowering (`CallBackKind::SimParamStr` → the `simparam_str` runtime,
returning a string pointer) already existed and is unchanged.

## Verification

`examples/simparamstr_examples/verify_simparamstr.py` (`ALL PASS`) — a model that sets its
conductance from `$simparam$str("analysis_name")` (read into a `string` variable
and compared): `g_dc` in dc/op, `g_ac` in ac, `g_tran` in tran. Running each
analysis and checking the terminal current confirms the correct string is returned
in each case. String comparison (`== "tran"`) and graceful handling of an unknown
name were also checked ad hoc. The numeric `$simparam(name[, default])` is
unchanged and still works, and every prior example folder still passes.

## Known limitations

- Only `"analysis_name"` and `"simulator"` are provided; other Verilog-AMS string
  parameters (e.g. `"cwd"`, hierarchical `"path"`/`"instance"`) are future work.
- The LRM variadic numeric form `$simparam("a","b")` (match any) is still
  single-argument (unrelated to this enhancement).
- Requires the accompanying ngspice build.
