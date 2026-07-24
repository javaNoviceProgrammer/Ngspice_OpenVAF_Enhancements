# Enhancement-314 — openvaf-r: constant-evaluation / literal-materialization robustness

Two independent defects found by grammar-based fuzzing (the E-307…E-313 campaign family),
both in how the compiler folds or materializes constant and literal input. One is a shipped
denial-of-service; the two others abort the overflow-checked build.

## (a) Integer const-fold overflow (three sites, one class)

Two hand-rolled integer constant evaluators used **unchecked i32 arithmetic**:

- **`hir/src/elaborate.rs`** — the Enhancement-91 bus-width folder. Its `parse_mul` already
  used `checked_mul(...)?`, but `parse_add`'s `+`/`-` (`acc += …` / `acc -= …`) and
  `parse_unary`'s negate (`-parse_unary(…)?`) were unchecked. It runs on every integer
  parameter/localparam default whenever the module text contains a `[`, so
  `localparam integer k = 2147483647 + 1;` (with any `[…]` declaration present) overflowed.
- **`mir_opt/src/const_eval.rs`** — Enhancement-286 made the MIR const-fold's `Iadd`/`Isub`/
  `Imul` wrapping and noted "eval_unary already used this convention", but **`Ineg` was
  missed** and still did `-val`, so negating `i32::MIN` (from `-(1<<31)`) overflowed.

All three aborted the overflow-checked build; the shipped release wrapped silently.

**Fix:** `elaborate.rs` uses `checked_add`/`checked_sub`/`checked_neg` — declining the fold
on overflow exactly as its `*` already did, so an un-foldable width is simply left unchanged
(the caller `fold_parameter_widths` handles `None` by leaving the declaration as written).
`const_eval.rs` uses `val.wrapping_neg()`, matching its own wrapping `Iadd`/`Isub`/`Imul`.

## (b) Unbounded replication → shipped compile-time DoS

`{N{…}}` replication materializes N copies of its operands at **compile time** — `infere_concat`
/ `lower_string_concat` build an `N·|elems|`-element list and, for strings, an
`N·|elems|`-character format string. A huge literal count — `{'d999999999{"x"}}` ≈ 10⁹ —
allocated gigabytes and **hung the compiler** on roughly one line of source, on both the
assertions and the shipped release build.

**Fix:** cap the count at 2²⁰ in `concat_rep_count` (`hir_ty`) and reject an abusive count with
the existing `InvalidReplicationCount` diagnostic. No legitimate source-level replication needs
more than a million copies, and the runtime object would be absurd regardless.

## Why it is safe

Checked/wrapping arithmetic is **identical to plain arithmetic on every non-overflowing
input**, and the replication cap only rejects counts above 2²⁰ — no real model has either, so
the 419-model corpus is unaffected (MIR unchanged; the one apparent diff during verification
was the committed binary's own run-to-run nondeterminism on a multi-module model, not this
change). The full 248-example regression passes under both solvers.

## Verification

`examples/vafconstlit_examples/verify_vafconstlit.py` — 4 checks under both solvers. The
replication check **fails on the pre-fix binary** (it hangs); the overflow model is a forward
correctness guard (the overflow defects are assertions-only — release always compiled — so the
authoritative before/after is the assertions build, which panics pre-fix and compiles cleanly
after). The overflow model simulates to `I = 1e-3·V`, and the abusive replication is rejected
in well under a second instead of hanging.

## Scope of change

`openvaf/hir/src/elaborate.rs` (2 hunks), `openvaf/mir_opt/src/const_eval.rs` (1 line),
`openvaf/hir_ty/src/inference.rs` (`concat_rep_count` cap). No interface change.
