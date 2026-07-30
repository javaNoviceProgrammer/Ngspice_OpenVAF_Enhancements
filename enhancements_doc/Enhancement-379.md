# Enhancement-379 — the workspace test suite runs, and stops deleting source

`cargo test --workspace` could not be used as a gate. It failed to build, and once
it built it **destroyed checked-in source**. Both are fixed; one part is repaired
and one part is quarantined, and the difference matters.

## 1. `verilogae` did not compile — 4 errors

The Python-binding crate had drifted behind the compiler it binds to.

* **`compiler_db.rs`** — `IntNumber::value()` returns `Option<i32>` (it is `None`
  for a literal too large for Verilog-A's 32-bit `integer`), and the call site
  still wrote `val.value() as f64`. This site wants a real-valued attribute
  default, so it takes the documented `value_as_f64()` fallback.

* **`back.rs`, `stub_callbacks`** — 13 missing `CallBackKind` variants: the
  string / file-I/O / `$sscanf` runtime (E-11, E-105, E-106), `ac_stim` (E-51) and
  the RNG builtins (E-10). Each signature is taken from
  `osdi::compilation_unit`'s `general_callbacks` rather than guessed: the call is
  built from the MIR arguments, so a stub with the wrong arity or return type is
  malformed IR, not a wrong number. `return None` is used only for `ScanBegin`,
  which returns nothing — the builder treats a missing callback as a no-op, so a
  value-returning one would leave its result undefined and abort codegen.

* **`back.rs`, two `ParamKind` matches** — `IsInitialStep`/`IsFinalStep` return
  `false`, following the `EnableIntegration`/`EnableLim` precedent (VerilogAE runs
  no analysis); `EventState(_)` joins the state group at `0.0`, being
  compiler-synthesised cross/above/timer state with nothing outside to supply it.

## 2. The suite deleted checked-in source

This is the serious half. Three `sourcegen` tests call `ensure_file_contents`,
which **overwrites** the file it generates. All three generators have fallen
behind the files they generate, so running the suite silently reverted shipped
work.

`generate_builtins` (found first, fixed alongside the verilogae work) strips six
builtins added by later enhancements — `$table_model`, `$realtime` (E-59),
`$rtoi`/`$itor` (E-104), `$fgetc` (E-107), `$ungetc` (E-108) — plus two
`ParamSysFun` methods without which `hir_def` does not compile, and silently
re-adds an `is_unsupported` gate over roughly thirty builtins that **are**
implemented (`zi_*`, `last_crossing`, `slew`, `transition`, the whole file-I/O
family). The checked-in file already carried a note that E-8's regeneration did
exactly this once before.

Both halves — `hir_def/src/builtin.rs` and `hir_ty/src/builtin/generated.rs` — are
hand-maintained and must agree index-for-index with `BuiltIn`, so regenerating one
and not the other is worse than regenerating neither. Neither is written now.

**A measurement trap worth recording:** I first reported the `hir_ty` half as "in
sync, 0 changed lines". It was not — I had measured it against a baseline the test
had *already* clobbered. Against git it differs too (117 entries versus the 111 the
generator emits). Snapshot before running a test that writes.

## 3. The two remaining tests: quarantined, not repaired

`ast::ast` and `osdi::gen_osdi_structs` are now `#[ignore]`d with the reason
recorded in the source. They are **disabled, not fixed**, because repairing them
means bringing the grammar and the header parser up to ~370 enhancements of hand
edits — its own piece of work.

* **`ast::ast`** rewrites the AST. Regenerating **deletes `DisableStmt`** entirely:
  `disable <block>`, Verilog-AMS's loop break, has *no rule in the grammar at all*
  and exists only in the checked-in file — and
  [Enhancement-375](Enhancement-375.md) depends on it. It also collapses `width()`
  from an `Option<Range>` + `widths()` pair into a single `AstChildren<Range>`,
  renaming accessors the parser and lowering call.

* **`osdi::gen_osdi_structs`** cannot parse the current `osdi_0_4.h` — it panics in
  `parse_ty` on `eat_ident().unwrap()`.

## Two real generator bugs fixed on the way, and kept

Both are correct independently of whether the tests are ever re-enabled:

* **`Rule::Rep(Seq(..))` is now lowered.** The grammar's
  `BitSelectExpr = base: Path ('[' index: Expr ']')*` — multi-dimensional selects
  from E-15 — used to panic with `unhandled rule`. It is the only non-comma-list
  repetition in the grammar; the rest are handled by `lower_comma_list`.
  `pluralize` also learned the irregular `index` → `indices`, since a bare `+s`
  would rename the accessor to `indexs`.

* **`Header::new` no longer unwraps the version parse.** Archived snapshots live
  beside the live header, and `osdi_0_4_enhancement1.h` strips to
  `"4_enhancement1"`, killing the whole generator with a bare
  `ParseIntError { kind: InvalidDigit }`. It now skips names that are not
  `osdi_<major>_<minor>.h`, consistent with how it already skips non-files.

## Verification

```
cargo test --release --workspace --features llvm18
  207 passed, 0 failed, 158 ignored
```

The 158 ignored are the pre-existing slow tests (`RUN_SLOW_TESTS=1`) plus the two
quarantined here. Before this change the suite did not build at all.

**Non-destructive**, checked explicitly: all five generated files —
`tokens/src/parser/generated.rs`, `syntax/src/ast/generated/{nodes,tokens}.rs`,
`hir_def/src/builtin.rs`, `hir_ty/src/builtin/generated.rs` — are byte-identical
to their committed versions after a full suite run.

Regression 303/303 (unchanged; this touches no simulation path).
