# Enhancement-310 — openvaf-r: a constant-branch fold left an SSA-invalid phi

The MIR-validity defect flagged by the same fuzzing campaign as
[Enhancement-307](Enhancement-307.md)/[308](Enhancement-308.md)/[309](Enhancement-309.md),
now resolved. It tripped `debug_assert!(cx.func.validate())` at `sim_back/src/lib.rs`.

## The defect

`simplify_cfg`'s `const_fold_terminator` folds a constant branch (`br TRUE|FALSE, a, b` →
`jmp`), removing the dead edge. When the dead destination's **only** predecessor was the block
being folded, this orphans it. `simplify_bb`'s orphan sweep normally then repairs the phis in
its successors — but it removes an orphan only when the block has **no live results**, a guard
that exists so `mir_autodiff`'s not-yet-placed instructions (which reference existing values as
raw operands before their own blocks are spliced in) are not dropped. So an orphan whose values
are still referenced in place is **left in the layout**, and a phi in one of its successors
keeps an edge labelled by that orphan naming a value that was only reachable through the deleted
edge — an SSA-invalid phi (`vX doesn't dominate use`).

It is the harder sub-case of the [Enhancement-287](Enhancement-287.md) family: E-287 handled
the orphan that *does* get removed; this is the orphan that survives the `has_live_results`
guard.

## Established: not a crash, and not a miscompile

* **Not a shipped crash** — a `debug_assert!`, so the release build compiled affected models
  without error.
* **Not a miscompile** — this was proven, not assumed. The fuzz reproducer was sanitised to
  clean, convergent math (`examples/vafcfgphi_examples/cfgphi_repro.va`), and its DC output was
  compared bit-for-bit against a valid-MIR reference built by disabling the offending fold in
  the same compiler: **max difference 0.000e+00**. LLVM lowered the invalid MIR to correct code.

Diagnosis method: per-pass validation inside `optimize()` localised the first invalid state to
`simplify_cfg`; per-sub-operation instrumentation localised it to `const_fold_terminator`; and
printing the fold's operands showed the failing case has `single_predecessor(dead_dst) ==
Some(bb)` with `dead_dst` carrying live results.

## The fix

Decline the fold in exactly that case — when it would orphan a `dead_dst` that still has live
results:

```rust
if self.cfg.single_predecessor(dead_dst) == Some(bb)
    && self.func.layout.block_insts(dead_dst)
        .any(|i| self.func.dfg.inst_results(i).iter().any(|&v| !self.func.dfg.value_dead(v)))
{
    return;
}
```

Declining an optimisation is **always output-preserving**, which is why this fix carries no
correctness risk: the branch is simply folded on a later sweep once the block can be cleaned up
safely. It leaves the E-287 fast path (fold + orphan-removal when the orphan has no live
results) untouched.

## Verification

* **Output preservation** — the reliable trigger's output is unchanged (guarded == pre-fix,
  0.000e+00), and across the corpus **34/34 model+deck pairs are bit-identical**, 0 differ
  (declining a fold cannot change semantics; verified empirically).
* **Validity** — the assertions build now passes `validate()` on all **332** corpus models
  (0 panics, was tripping) and on all three reduced reproducers.
* **Fuzzing** — a **15000-seed re-fuzz** against the assertions build finds **0** occurrences
  of this assert (or of the E-307/308/309 crashes): `{ok: 15000, ICE: 0, ASSERT: 0}`.
* **Corpus replay** — 332 models, identical pass/fail on the old and new compilers.

`examples/vafcfgphi_examples/verify_vafcfgphi.py` is a forward correctness guard: the model
reduces at DC to a linear conductance, and its response is asserted **exactly linear** to
machine precision. (It legitimately passes on both compilers, since the defect was benign and
assertions-only — see the suite's note.)

## Scope of change

`OpenVAF-master-20260610/openvaf/mir_opt/src/simplify_cfg.rs`, `const_fold_terminator` — one
decline-guard, 23 lines.
