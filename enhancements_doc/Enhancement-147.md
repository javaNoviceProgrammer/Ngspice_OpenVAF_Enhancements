# Enhancement-147 — nested `?:` no longer takes exponential time to compile

A deep robustness campaign against `openvaf-r` (adversarial inputs, the full
production-model corpus, and thousands of mutation-fuzzing iterations) surfaced one
high-severity compiler bug: **a chain of nested ternary (`?:`) expressions took
`O(2ⁿ)` time to compile**, so a module with ~30 nested conditionals — easily
produced by macros in a real device model — hung the compiler indefinitely.

## Root cause

The body validator in `hir_ty/src/validation/body.rs` visits every expression in
`validate_expr`, whose `match` ends by recursing into the children:

```rust
_ => ()
}
self.parent.body.exprs[expr].walk_child_exprs(|child| self.validate_expr(child))
```

Arms that fully validate their own operands `return` early to skip that generic
walk — the `Call` and `Path` arms both do. The **`Select` (ternary) arm did not**:
it validated `cond`, `then_val` and `else_val` via `validate_condition`, and then
*fell through* to `walk_child_exprs`, which validated `then_val` and `else_val` a
**second** time. Each ternary therefore validated its branches twice; for a chain of
N nested `?:` this compounds to **2ⁿ** validations.

Profiling a hanging compile confirmed it exactly — an unbounded
`validate_expr → validate_condition → validate_expr → …` recursion with a doubling
call count.

## The fix

Add a `return;` at the end of the `Select` arm, matching the `Call` and `Path` arms.
The arm already validates all three children (`cond`, `then_val`, `else_val`), so the
generic `walk_child_exprs` was pure redundant work — removing it is behaviour-
preserving and turns validation from `O(2ⁿ)` into `O(N)`.

```
depth 40:  hang (>30 s)   →   0.09 s
depth 160: (2¹⁶⁰, hopeless) →   0.11 s
depth 2000:                →   1.6 s   (linear)
```

## Verification

- **`examples/nested_cond_examples/verify_nested_cond.py` (7/7):** nested `?:` chains
  of depth 20/40/80/160 all compile in < 0.2 s; compile time grows ~linearly
  (`t(160)/t(20) ≈ 1.2`, not exponential); and a nested-ternary model still compiles
  to a valid `.osdi` and computes the correct piecewise value in ngspice
  (`I(2.5 V) = 2.5/3 kΩ = 833.3 µA`).
- **Behaviour-preserving:** every one of the **117 production CMC models** (BSIM,
  PSP, HICUM, MEXTRAM, VBIC, EKV, …) compiles to the **identical verdict** before and
  after the fix (0 flips in a head-to-head run), and BSIM4 (12.6 k lines) still
  compiles in ~2.3 s.
- **Unit tests:** `hir_ty`, `hir`, `hir_lower` and `sim_back` test suites pass with
  no snapshot changes.

## The robustness campaign (context)

The bug was found by a systematic robustness sweep, which also confirmed the
compiler is otherwise solid:

- **117 real production models** — 0 crashes / hangs / panics.
- **~50 adversarial hand-crafted inputs** (unterminated constructs, malformed
  numbers, macro bombs, duplicates, unicode/null bytes, …) — all rejected cleanly;
  no accepted-invalid inputs.
- **4000 mutation-fuzzing iterations** on real models — **0 panics, 0 segfaults**;
  the compiler never crashed on random/garbage input.

Lower-severity findings that remain (all require pathological input a human or real
model would never write, and abort cleanly rather than hang) are documented as
follow-ups: a recursive-descent **stack overflow** on extreme expression nesting
(≈ 4 k–32 k deep unary / binary / parenthesised / call chains); an uncapped
**`include` self-recursion** (a file that `` `include ``s itself) overflowing the
stack; and a **huge array dimension** (`real x[0:100000000]`) exhausting memory.
Adding a parse-time nesting-depth limit and an include-depth cap (mirroring the
existing macro-recursion cap) would turn these into clean diagnostics.

## Scope

A one-line, behaviour-preserving correctness/performance fix to the body validator,
eliminating an exponential-time compile on nested conditional expressions. Confined
to `hir_ty/src/validation/body.rs`; no change to generated code.
