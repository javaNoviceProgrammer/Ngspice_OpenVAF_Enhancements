# vafgvnunreach_examples — Enhancement-309

**Global value numbering crashed on a user instruction in an unreachable block.**

When an instruction's congruence class changes, GVN re-queues every instruction that **uses**
it, looking up each user's position with

```rust
self.dfs_map.inst_to_dfs[inst].unwrap_unchecked()
```

But `DFSMapping::populate` only numbers instructions reachable through `cfg_postorder`, so a
user living in an **unreachable** block has no DFS id. `unwrap_unchecked` then:

* under **debug-assertions**, called `PackedOption::unwrap()` and panicked at
  `lib/stdx/src/packed_option.rs:60`;
* in **release**, returned the reserved sentinel id, which `touched_insts.insert` used as an
  out-of-range `BitSet` index —

so the **shipped** compiler crashed either way (*"OpenVAF encountered a problem and has
crashed!"*).

## How it was found

The same grammar-based middle/back-end fuzzer as [E-307](../../enhancements_doc/Enhancement-307.md)
and [E-308](../../enhancements_doc/Enhancement-308.md) — seed 6716, at roughly 1 in 8000.

## The fix

Skip users with no DFS id. An un-numbered user is in an unreachable block, so it is not in
the GVN work list (the solver only iterates `dfs_to_inst`) — re-queuing it would be a no-op.
This matches how `get_rank`, in the same file, already tolerates the identical `None`:

```rust
if let Some(dfs_id) = self.dfs_map.inst_to_dfs[inst].expand() {
    self.touched_insts.insert(dfs_id);
}
```

## Verify

```bash
python3 verify_vafgvnunreach.py
```

Two checks under both solvers: the reproducer compiles (it crashed before); and a
common-subexpression-heavy model that GVN **actively optimises** still computes the exact
closed-form result `I = 4·V·g + (V·g)²`, proving the fix does not disturb the pass on
reachable code. The suite fails on the pre-fix compiler.

## Campaign summary

E-307, E-308 and E-309 are the three distinct compiler CRASHES found by this fuzzing
campaign, all now fixed: a 12000-seed re-fuzz against the fully-fixed compiler shows zero
occurrences of any of them. That deeper run also tripped one `debug_assert!` MIR-validation
failure at `sim_back/src/lib.rs:175` (seed 11633) -- NOT a shipped crash (the release build
compiles it fine), but the same assertions-only malformed-MIR class as E-286..E-294. It is
documented for a separate follow-up.
