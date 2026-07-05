# Enhancement-60 — multiple analog blocks: validation deliverable (version11)

This document records the Enhancement-60 probe of **multiple `analog` /
`analog initial` blocks per module** (Verilog-AMS LRM 6.2: several blocks
"shall behave as if they combine into a single analog block in the order
they appear"). **No defects were found — the feature is fully supported by
construction** — so, like Enhancement-57, the deliverable is the validation
itself: a probe battery, a pinned example suite, and this write-up. No
compiler or ngspice source changes.

## Why it works by construction

`hir_def/src/body.rs` collects a module's behavioural body as

```rust
body.entry_stmts = if initial {
    ast.analog_initial_behaviour().map(|stmt| ctx.collect_stmt(stmt)).collect()
} else {
    ast.analog_behaviour().map(|stmt| ctx.collect_stmt(stmt)).collect()
};
```

— an iterator over **every** analog (respectively `analog initial`) block
of the module, collected into `entry_stmts` **in document order**. That is
literally the LRM's as-if-concatenated semantics; every downstream stage
(type inference, lowering, autodiff, the DAE builder, OSDI) already
consumes `entry_stmts` as a list and sees one concatenated body. There is
no single-block assumption anywhere to fix.

## The probe battery (9 corners, zero defects)

| corner | result |
|---|---|
| contributions to one branch from several blocks | accumulate exactly (1+2 mS → 3 mS) |
| module variable written in block 1, read in block 3 | shared, in order |
| execution order (`$strobe` in consecutive blocks) | source order preserved |
| `analog function` declared **between** two blocks | callable from later blocks |
| module declarations (parameter/branch/var) **after** a block that uses them | resolve (module-scope, order-free) |
| events split across blocks (`cross` in one, `final_step` in another; `initial_step` counters) | all fire, once each |
| `ddt()` of a charge computed in an earlier block | correct reactive residual |
| multi-block module **instantiated** (E-5 elaboration re-render) | both blocks survive flattening — series current exact to 12 digits |
| two `analog initial` blocks | compose in order (`g = 1m; g = g + 1m` → exactly 2 mS) |

Two behaviors verified as *correctly rejected / consistent* rather than gaps:

- **duplicate named child blocks** (`begin : work` in two analog blocks):
  clean `'work' was already declared in this scope` error — named blocks
  live in the module namespace, so hierarchical references (`inst.work.t`)
  must stay unambiguous;
- `V(a,c) <+` in one block and `I(a,c) <+` in another compiles — identical
  to the single-block switch-branch behavior (LRM value-retention rules),
  i.e. multi-block introduces no inconsistency.

## Examples (`multianalog_examples/`, 6 checks, ALL PASS)

`verify_multianalog.py`: [1] three-block accumulation to exactly 3 mS +
cross event in the middle block fires; [2] strobes print in source order +
ordered `analog initial` composition (2 mS exact); [3] a multi-block module
survives instance flattening (series current exact to 12 digits); [4] the
duplicate-named-block diagnostic.

## Notes

- Verilog-A 1.0 originally allowed only one analog block per module;
  Verilog-AMS 2.2+ relaxed this, and openvaf-r follows the relaxed (current
  LRM) rule. Accepting the multi-block form is a superset of Annex C either
  way — no legal single-block model changes meaning.
- Regression: **no compiler/ngspice source changes in this enhancement**;
  the Enhancement-59 full regression (55 suites, crate tests, 92/92 corpus)
  stands, plus the new suite's 6 checks.
