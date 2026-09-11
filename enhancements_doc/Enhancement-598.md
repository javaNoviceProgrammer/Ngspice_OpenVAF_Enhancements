# Enhancement-598: `$simparam$str(name, default)` — the non-fatal string form

**Scope:** `openvaf/hir_ty/src/builtin.rs` (the `SIMPARAM_STR` signature family),
`openvaf/hir_lower/src/expr.rs` (the lowering), `openvaf/hir_ty/src/validation/body.rs`
and `validation.rs` (the L025 name check and its help), `openvaf/hir/src/lib.rs`
(re-exports), `examples/simparamstrdef_examples/` (new, 13 checks per solver);
handbook [§2](../docs/handbook/02-verilog-a-language.md) row *`$simparam`*, and the
compliance document. **Compiler only; ngspice is unchanged.** Finding F3 of the
2026-09-10 integration hunt
([`docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md`](../docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md)).

**Suites:** [`simparamstrdef_examples`](../examples/simparamstrdef_examples/) 13 of 13 per
solver, both solvers; `simparamstr`, `simparamdiag`, `plusargs` unchanged; `cargo test`
of `hir_ty`, `hir_lower` and `hir` green; full sweep 492 of 492 with the rebuilt
compiler.

## What was wrong

```
error: invalid argument count: expected 1 arguments but found 2
    $strobe("module=%s", $simparam$str("module", "dflt"));
```

LRM 9.15.1 gives the string form the same optional second argument as the numeric one:
`$simparam$str(param_name [, default_value])`. `$simparam(name, default)` is the
documented non-fatal form and works; the string variant's front-end signature was a
single one-argument entry, so the call was refused at compile time — although the
backend had carried `CallBackKind::SimParamStrOpt` → `simparam_str_opt` since
Enhancement-215, for the plusargs lowering. Without it, `$simparam$str("instance")`,
`"module"` and `"path"` — which ngspice deliberately does not serve, the channel
carrying no instance identity — were a compile-time L025 warning followed by a
run-time `$fatal` at the operating point, with no way for a portable model to ask
politely.

## What changed

- `SIMPARAM_STR` is a two-signature family, `SIMPARAM_STR_NO_DEFAULT` and
  `SIMPARAM_STR_DEFAULT(Val(String), Val(String))`, added at the end as the table
  requires. The default may be a literal, a string parameter or a string variable, as
  for the numeric form.
- The two-argument form lowers to the existing `SimParamStrOpt` callback, which returns
  the served value or the default and never sets the fatal flag.
- The L025 unknown-name check applies to the one-argument forms of both spellings only,
  as it already did for `$simparam`; the note under the warning now spells the help in
  the same spelling as the call, `$simparam$str("instance", "<default>")`.
- A non-string default is a type error, three arguments an arity error.

## Verification

| check | result |
|---|---|
| `$simparam$str("instance", "dflt")` | compiles, no L025 |
| `$simparam$str("instance", 5)`; three arguments | "expected string value"; "expected at most 2 arguments" |
| `$simparam$str("instance")` | still L025, with the help in the string spelling |
| at the operating point: `analysis_name`/`simulator` with a default | the served values (`dc`, `ngspice`) |
| `instance`, `module`, `path` with a literal, a string parameter and a string variable as default | the default, and the run completes |
| control: `$simparam$str("instance")` alone, its result used | `unknown $simparam$str "instance"`, the run aborted, as before |
| `parameter string q = $simparam$str("module", "d")`, `q2 = $simparam$str("simulator", "?")` | `q` = d, `q2` = ngspice, both on `showmod` |

Full sweep 492 of 492 on both solvers with the rebuilt compiler.
