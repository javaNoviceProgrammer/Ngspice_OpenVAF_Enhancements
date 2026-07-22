# Enhancement-287 — openvaf-r: a folded-away branch orphaned a block, leaving a stale phi edge

```verilog
if (flicker_noise(1.0, 1.0) > 1.0)
    x = $temperature;
else
    y = V(a, b);
y = y - x;              // both read on a path where the other was written
```

A noise operator in an `if` **condition** is zero outside noise analysis, so the
optimizer can prove the branch constant and fold it. Folding it produced a function
that violates SSA — and because the MIR verifier is a `debug_assert!`, the release
compiler carried that malformed function forward without a word.

## Root cause

`mir_opt/simplify_cfg.rs`, `const_fold_terminator` rewrites a branch with a constant
condition into a jump, and calls `remove_phi_edges(dead_dst, bb)` to clean up. That
call fixes the phis **inside** the newly-unreachable successor — but the phis that
actually go stale are the ones in *its* successors, which keep an edge labelled with
the now-orphaned block, naming a value that was only ever available through the edge
just deleted:

```
v22 = phi [v31, block2], [v20, block3]     // block2 is now unreachable
                                           // v31 is defined in block11, which
                                           // reaches block3 -- not block2
```

`simplify_bb` is the pass that collects predecessor-less blocks (and does prune their
successors' phi edges), but it only sees the orphan on a **later sweep**, and blocks
are visited in layout order, so the orphan is typically already behind the cursor.
The sweep never ran again, because this branch of `const_fold_terminator` — unlike its
`then_dst == else_dst` sibling three lines above — **never set `local_changed`**. With
no change flagged, `iteratively_simplify_cfg` stopped, orphan still in place.

## Fix

Set `self.local_changed = true` after const-folding the branch, so the driver loop
sweeps again and `simplify_bb` collects the orphan (and its stale phi edges) as it was
always meant to. The change is monotone — a folded branch becomes a jump and cannot
fold again — so the loop still terminates.

## Verification

`examples/vafcodegen_examples/verify_vafcodegen.py` — `orphanblock.va` compiles and
simulates (`I == V/1k`, the noise term being zero in the large-signal domain). The
authoritative check is that an assertions-enabled compiler now accepts the module,
where it previously reported `v31 doesn't dominate use (block11 !dom block2)`. This
pass runs on **every** model, so the whole 248-model example corpus was recompiled
release-vs-release: zero regressions.

## Scope

One source file (`openvaf/mir_opt/src/simplify_cfg.rs`), one statement. No public
interface or OSDI ABI change.
