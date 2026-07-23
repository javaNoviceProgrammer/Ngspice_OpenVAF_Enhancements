# vafcfgphi_examples — Enhancement-310

**A constant-branch fold left an SSA-invalid phi (the `sim_back/lib.rs` validate assertion).**

`simplify_cfg`'s `const_fold_terminator`, when it folds a constant branch and removes the
dead edge, can **orphan** the dead destination. The orphan sweep in `simplify_bb` normally
repairs the phis in that block's successors — but only when the block has **no live results**
(a guard that protects `mir_autodiff`'s not-yet-placed instructions). An orphan whose values
are still referenced in place therefore survives, and a phi in one of its successors keeps an
edge naming a value that was only reachable through the deleted edge — an **SSA-invalid phi**.

That tripped `debug_assert!(cx.func.validate())` at `sim_back/src/lib.rs`.

## Not a crash, not a miscompile — established, not assumed

* **Not a shipped crash.** It is a `debug_assert!`, so the release build compiled the affected
  models without error.
* **Not a miscompile.** A reliable, finite-math, convergent reproducer was sanitised from the
  fuzz seed (this suite's `cfgphi_repro.va`), and its output was compared, bit-for-bit,
  against a valid-MIR reference (the same compiler with the offending fold disabled): **max
  difference 0.000e+00**. LLVM lowered the invalid MIR to correct code.

## The fix

Decline the fold in exactly the unsafe case: when removing the edge would orphan a `dead_dst`
that still has live results. Declining an optimisation is **always output-preserving**, so no
model's numbers change; the branch is folded later once the block can be cleaned up safely.

```rust
if self.cfg.single_predecessor(dead_dst) == Some(bb)
    && dead_dst_has_live_results { return; }   // decline; fold it later, safely
```

## What this suite shows

Because the defect is benign and **assertions-only**, a suite driven by the release binary
passes on **both** the pre-fix and post-fix compilers — it cannot "fail on the pre-fix binary"
the way the crash suites do. The authoritative before/after evidence is:

* an **assertions-enabled** build panics at `sim_back/lib.rs` before the fix and compiles
  cleanly after (0 validate panics across the 332-model corpus, and **0 asserts in a
  15000-seed re-fuzz** — was hitting this class before);
* the whole **332-model corpus** produces **bit-identical** output pre/post.

What the suite guards is **forward correctness**: the model reduces at DC to a linear
conductance, so its response must stay finite and **exactly linear** (checked to machine
precision). A future change that turned this into an actual miscompile would introduce a kink.

## Verify

```bash
python3 verify_vafcfgphi.py
```
