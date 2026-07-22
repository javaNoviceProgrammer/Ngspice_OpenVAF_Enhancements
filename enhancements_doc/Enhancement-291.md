# Enhancement-291 — openvaf-r: `max`/`min`/`abs` in a `case` default arm left a block unsealed

```verilog
case (V(a, b))
    5.0: y = 11.0;
    default: y = max(3.0, 7.0);
endcase
```

aborted the compile with:

```
FunctionBuilder finalized, but block block4 is not sealed
```

The discriminator is sharp: `pow(2,3)` in the same arm is fine, `max` in an **item**
arm is fine, `max` outside a `case` is fine. Only a branch-lowering builtin in the
**default** arm failed.

## Root cause

`max`, `min` and `abs` do not lower to a single instruction — they lower through
`make_cond` to a real select with its own then/else/merge blocks. `pow` and friends
emit one instruction and open no blocks.

`hir_lower/src/stmt.rs`, `lower_case` creates a fall-through block per case item and
switches to it, but leaves it to be sealed by an `ensured_sealed()` — either at the top
of the next iteration or, for the last item, after the default arm's body is lowered.
`ensured_sealed()` seals whatever block the builder is currently positioned in. When
the default arm's body opens blocks of its own, it leaves the builder positioned on
**its** merge block, so the seal lands there (already sealed, a no-op) and the case's
fall-through block is never sealed at all.

## Fix

Seal the fall-through block where it is created. The branch just emitted is the only
way into it, so all of its predecessors are already known and sealing it immediately is
correct:

```rust
self.ctx.ins().branch(cond, body_head, next_block, false);
self.ctx.seal_block(next_block);
self.ctx.switch_to_block(next_block);
```

The later `ensured_sealed()` calls check `is_sealed` first, so they become no-ops for
this block rather than double-sealing it.

## Verification

`examples/vafcodegen_examples/verify_vafcodegen.py` — `casemax.va` compiles, and the
`case` still selects the right arm: `V=2` takes the default (`max(3,7) = 7`), `V=5`
takes the item arm (`11`). Also checked for `min`, `abs`, nested combinations, an
integer discriminant, and `casex`.

## Scope

One source file (`openvaf/hir_lower/src/stmt.rs`), one statement. No public interface
or OSDI ABI change.
