# Enhancement-148 — compiler hardening: parser depth, include cap, array cap

The robustness campaign behind [Enhancement-147](Enhancement-147.md) fixed the one
*plausible-in-real-code* failure it found (exponential-time nested `?:`). It also
turned up three lower-severity ways to make `openvaf-r` crash or hang on
**pathological** input — input a human or real device model would never write, but
which a robust compiler should still reject cleanly rather than die on. This
enhancement closes all three.

## What was fixed

| Pathological input | Before | After |
|---|---|---|
| deeply nested / chained expression (`----…x`, `x+1+1+…`, `((…))`, `sin(sin(…))`, `1?…:0`) | recursive-descent **stack overflow** (`SIGABRT`), or a later recursive tree traversal overflowing | clean parse error |
| a file that `` `include ``s itself | uncapped include recursion → **stack overflow** | clean *"nests too deeply"* error |
| an absurd array / bus / instance range (`real x[0:100000000]`) | expanded element-by-element → **memory exhaustion / hang** | clean *"too large"* error |

### 1. Parser expression-depth limit

`parser`'s Pratt expression parser recurses through `atom_expr` for every level of
nesting (prefix operators, parentheses, call arguments, ternary branches) and builds
a left-leaning tree for operator chains. Both an over-deep recursion *and* an
over-deep tree (which later passes recurse over) could overflow the stack. A shared
`expr_depth` counter — incremented on each `atom_expr` (recursion) and per operator
in the `expr_bp` loop (chain length) — bounds the total expression-tree depth at
**1000** (real models nest expressions a few dozen deep) and recovers to the next
statement boundary when exceeded.

### 2. `` `include `` recursion cap

The preprocessor's `include_file` recursed into `process_file`, which processes the
included file's own `` `include ``s — with no bound, so a self-including file
overflowed the stack. An `include_depth` counter caps nesting at **64** and emits a
new `IncludeRecursionLimit` diagnostic, mirroring the existing macro-recursion guard
(Enhancement-65).

### 3. Array / bus / instance element cap

An array-shaped declaration is flattened into one scalar element per index, so an
unbounded range materialized (and, for instance arrays, *rendered*) millions of
entries. A shared `array_elem_count` helper caps the expansion at **2²⁰ ≈ 1.05 M**
elements and emits a new `ArrayTooLarge` diagnostic (degrading to a single scalar so
compilation proceeds). It is applied at every expansion site: variable arrays,
parameter arrays, net/port buses, array function returns (`hir_def` item-tree
lowering), and instance arrays (both the item-tree lowering and the `hir` elaboration
pass, which re-expands them into rendered text).

## Files

`parser/src/{parser.rs, grammar/expressions.rs}`,
`preprocessor/src/{diagnostics.rs, processor.rs}`,
`basedb/src/diagnostics/preprocessor_error.rs`,
`hir_def/src/item_tree.rs`, `hir_def/src/item_tree/{diagnostics.rs, lower.rs}`,
`hir/src/elaborate.rs`.

## Verification

`examples/robustness_examples/verify_robustness.py` (17/17): each pathological input
(5 deep-expression shapes, self-include, and 4 huge-array kinds — variable,
parameter, net bus, instance) now exits with a **clean error in well under a second**
— no crash, no hang — with the expected diagnostic text; and valid deep-but-
reasonable input (nested ternary depth 30, parentheses depth 100, a 100-term sum, and
small variable/instance arrays) still compiles.

**Behaviour-preserving:** all **117 production CMC models** compile to the identical
verdict before and after (0 flips in a head-to-head run) — no real model comes near
any limit — and the `parser`, `preprocessor`, `hir_def`, `hir_ty` and `sim_back`
unit-test suites pass with no snapshot changes.

## Scope

Turns three pathological-input crash/hang paths into clean, bounded diagnostics. The
limits (expression depth 1000, include depth 64, array elements ~1 M) are far beyond
anything real Verilog-A produces. With this the robustness campaign's findings are
fully resolved.
