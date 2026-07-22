# Enhancement-294 — openvaf-r: rewriting a `Branch` into a `Jump` left its condition in the use list

```verilog
parameter real p = 1.0;
analog begin
    if (p < 0.0)
        $fatal(0, "p must be nonnegative");
    I(a, c) <+ V(a, c) / 1.0e3;
end
```

Compiling this left the module MIR with a **dangling use record**. The verifier reports:

```
thread 'main' panicked at openvaf/mir/src/dfg/uses.rs:278:9:
index out of bounds: the len is 0 but the index is 0
```

## Root cause

A `Branch` carries exactly one value operand — its condition — while a `Jump` carries
none. Every branch-to-jump rewrite must therefore retire that operand's entry in the
condition value's use list. Two of the four sites did not; they simply overwrote the
instruction:

```rust
self.func.dfg.insts[terminator] = InstructionData::Jump { destination: else_dst };
```

The use record survives, still linked into the condition value's list, naming **operand 0
of an instruction that now has zero operands**. Reading it (`use_to_value` →
`insts.args(parent)[parent_idx]`) indexes an empty slice.

The two offenders:

- `mir_opt/simplify_cfg.rs`, `simplify_bb`'s **empty-exit-block** rewrite (both the
  `then_dst` and `else_dst` arms) — the one this reproducer hits;
- `mir_opt/dead_code_aggressive.rs`, the dead-block terminator rewrite — the same defect,
  found by inspecting the class rather than by a failing model.

The two rewrites in `const_fold_terminator` do it correctly, one with `zap_inst` and one
with `detach_operand`, which is what made the omission visible as an inconsistency.

## Why this shape and not another

`$fatal` exits the analog block, so its arm becomes an **empty exit block** — exactly the
case `simplify_bb` rewrites. The condition must be a **parameter** compare: with a node
voltage the arm is not an empty exit block and the rewrite never fires. `$finish` does not
trigger it either; only `$fatal` produces this block shape. That narrowness is why a
single module out of the whole corpus reached it.

## Fix

`zap_inst` the terminator before overwriting it, at both sites — the same idiom
`const_fold_terminator` already uses.

## What this did and did not cost

Being honest about severity: the stale entry did **not** produce a wrong `.osdi`, and I
could not construct a release build that fails because of it. Release builds never run the
MIR verifier (it sits behind a `debug_assert!`), and the passes that would trip over the
record — `replace_uses`, `use_set_value`, both of which index `args[parent_idx]` through
bounds checks that *are* active in release — happen not to touch that value again in any
model in the corpus.

So this is a broken data-structure invariant with a latent release-crash hazard, not a
demonstrated miscompilation. It is worth fixing on its own terms: it is the last thing
standing between the compiler and a clean assertions-enabled run over the whole corpus,
which is the audit that found Enhancements 286-293 in the first place.

## A related latent case, deliberately left alone

`mir/src/dfg/instructions.rs`, `update_inst_uses`, retires surplus use records with
`self.insts.uses[inst].truncate(arg_len, pool)` — which drops them from the
*instruction's* list without detaching them from the *value's*. That is the same class.
It is not currently reachable: every caller runs `zap_inst` first, so the surplus records
are already detached, and `attach_use`'s own `debug_assert!` would have fired across the
corpus otherwise. Changing it would be an unverifiable edit to core DFG code, so it is
recorded here rather than patched speculatively.

## Verification

`examples/vafcodegen_examples/verify_vafcodegen.py` — `staleuse.va` compiles and simulates
(`I == V/1k`). The authoritative evidence is the corpus replay under an assertions-enabled
compiler: **all 255 models now compile clean, 0 latent defects**, where `simctrl_demo.va`
previously aborted. Release-vs-release across the same 255 models: **0 regressions**;
`cargo test` 69 passed / 0 failed with no MIR or OSDI snapshot moved.

## Scope

Two source files (`openvaf/mir_opt/src/simplify_cfg.rs`,
`openvaf/mir_opt/src/dead_code_aggressive.rs`). No public interface, OSDI ABI, or
generated-code change.
