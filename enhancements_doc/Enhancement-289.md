# Enhancement-289 — openvaf-r: `llvm.ctlz` was declared without its type suffix

`$clog2(n)` with a runtime argument produced a module LLVM rejects:

```
Intrinsic name not mangled correctly for type arguments! Should be: llvm.ctlz.i32
ptr @llvm.ctlz
```

## Root cause

`llvm.ctlz` is an **overloaded** LLVM intrinsic: its name must carry the type it
operates on. `mir_llvm/src/intrinsics.rs` registered the bare name —

```rust
ifn!("llvm.ctlz", fn(t_i32, t_bool) -> t_i32);
```

— and `mir_llvm/src/builder.rs` looked it up under the same bare name. The
neighbouring overloaded entries are all spelled correctly (`llvm.pow.f64`,
`llvm.sqrt.f64`, `llvm.ceil.f64`, `llvm.lround.i32.f64`); `ctlz` is the only one
missing its suffix.

`ctlz` backs `$clog2`, which computes `bit_width(n-1)` — so every model calling
`$clog2` on a non-constant argument emitted invalid IR. As with Enhancement-288, the
module verifier that reports this is a `debug_assert!`, so release builds shipped it.

This one was found by replaying the committed example corpus through an
assertions-enabled compiler: `clog2_examples/clog2_demo.va` — a model that had been
shipping and simulating correctly — was rejected.

## Fix

Register and look it up as `llvm.ctlz.i32` (both `intrinsics.rs` and `builder.rs`,
including the "intrinsic not found" message).

## Verification

`examples/vafcodegen_examples/verify_vafcodegen.py` — `hypotclog2.va` checks
`$clog2(100) == 7` with `pn` a runtime parameter. The pre-existing
`clog2_examples/verify_clog2.py` continues to pass, and now also passes under an
assertions-enabled compiler.

## Scope

Two source files (`openvaf/mir_llvm/src/intrinsics.rs`, `openvaf/mir_llvm/src/builder.rs`).
No public interface or OSDI ABI change.
