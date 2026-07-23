# Enhancement-309 — openvaf-r: GVN crashed on a user instruction in an unreachable block

The third and final compiler crash from the grammar-based middle/back-end fuzzing campaign
that produced [Enhancement-307](Enhancement-307.md) and
[Enhancement-308](Enhancement-308.md).

Global value numbering, when an instruction's congruence class changes, re-queues every
instruction that **uses** it, looking up each user's DFS position:

```rust
for use_ in func.dfg.inst_uses(inst) {
    let inst = func.dfg.use_to_operand(use_).0;
    let dfs_id = self.dfs_map.inst_to_dfs[inst].unwrap_unchecked();   // <-- crash
    self.touched_insts.insert(dfs_id);
}
```

`DFSMapping::populate` numbers only instructions reachable through `cfg_postorder`, so a user
that lives in an **unreachable** block has no DFS id. `unwrap_unchecked` is defined as

```rust
pub fn unwrap_unchecked(self) -> T {
    if cfg!(debug_assertions) { self.unwrap() } else { self.0 }
}
```

so under debug-assertions it called `PackedOption::unwrap()` and panicked at
`packed_option.rs:60`; and in release it returned the reserved sentinel value, which
`touched_insts.insert` then used as an **out-of-range `BitSet` index** — crashing the
**shipped** compiler all the same. *"OpenVAF encountered a problem and has crashed!"* on valid
Verilog-A, at roughly 1 in 8000 fuzzed models (seed 6716).

## The fix

Skip users with no DFS id. An un-numbered user is in an unreachable block and is therefore not
in the GVN work list — the solver only ever iterates `dfs_to_inst` — so marking it touched
would be a no-op. This is exactly the tolerance `get_rank`, a few lines up in the same file,
already applies to the identical `None` (returning `u32::MAX` for an un-numbered instruction):

```rust
if let Some(dfs_id) = self.dfs_map.inst_to_dfs[inst].expand() {
    self.touched_insts.insert(dfs_id);
}
```

The two remaining `unwrap_unchecked` sites in this function operate on the instruction
currently being processed, which comes from `dfs_to_inst` and is always numbered, so they are
safe and unchanged.

## Verification

`examples/vafgvnunreach_examples/verify_vafgvnunreach.py` — two checks under both solvers. The
reproducer compiles (it crashed before); and a common-subexpression-heavy model that GVN
**actively optimises** still computes the exact closed-form result `I = 4·V·g + (V·g)²` — which
proves the fix leaves the pass's optimisation of reachable code untouched. The suite fails on
the pre-fix compiler. The full corpus (330 models) replays with an identical pass/fail split
on the old and new compilers.

A **12000-seed re-fuzz** against the fully-fixed compiler shows **zero** occurrences of this
crash or of the E-307 and E-308 crashes — the three distinct compiler crashes this campaign
found are all closed.

## Scope of change

`OpenVAF-master-20260610/openvaf/mir_opt/src/global_value_numbering.rs`,
`update_congurence_class`.
