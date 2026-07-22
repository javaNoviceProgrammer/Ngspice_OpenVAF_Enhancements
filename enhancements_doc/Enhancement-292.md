# Enhancement-292 — openvaf-r: small-signal pruning indexed a key its own replay never inserted

A fuzzer input routing noise waves through `idt` into nested `laplace_nd` coefficient
arrays aborted the compile with:

```
thread 'main' panicked at openvaf/sim_back/src/topology/small_signal_network.rs:288:49:
no entry found for key
```

## Root cause

`prune_small_signal` moves a linear contribution out of the small-signal network into
its own dimension. Its own doc comment says this happens **"where possible"** — but
whether it *is* possible is decided by two different pieces of code:

* `collect_linear_contributes` classifies the contribution as linear in the value, and
* the replay inside `create_dimension` is what actually **builds** the per-dimension
  value and records it in `val_map`.

The replay deliberately declines several shapes — an `fmul` whose *both* operands
depend on the dimension, or any opcode that falls through to its catch-all — so the
two analyses can disagree. When they did, the classifier produced a contribution the
replay had never mapped, and:

```rust
let dimension = self.val_map[&contribute];      // panics: no entry found for key
```

took the whole compile down.

## Fix

Treat the disagreement as what it is — pruning is a best-effort optimization — and give
up on that value instead of crashing:

```rust
if contributes.iter().any(|c| !self.val_map.contains_key(c)) {
    self.func.dfg.replace_uses(placeholder, val);
    continue;
}
```

The `replace_uses` on the bail-out path matters: `prune_small_signal` creates an
**invalid placeholder value** before the replay and resolves it at the end, so an early
`continue` must resolve it too or an invalid value survives in the function. The replay
instructions that are now unused are dead code the later DCE pass removes.

## Verification

`examples/vafcodegen_examples/verify_vafcodegen.py` — `ssprune.va` (the reduced
reproducer) compiles, where the pre-fix compiler exited 101. Behaviour-preserving for
every model where the two analyses agree, which is all of them: the full 248-model
example corpus compiles release-vs-release with zero regressions, including the noise
and RF suites that exercise this pass most heavily.

## Scope

One source file (`openvaf/sim_back/src/topology/small_signal_network.rs`). No public
interface or OSDI ABI change.
