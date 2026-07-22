# Enhancement-288 — openvaf-r: `hypot` was declared with one parameter and called with two

```verilog
analog I(a, b) <+ hypot(V(a), V(b));
```

produced a module LLVM rejects:

```
Incorrect number of arguments passed to called function!
  %28 = call double @hypot(double %19, double %24)
```

## Root cause

`mir_llvm/src/intrinsics.rs` declares the maths functions the code generator calls.
`hypot` needs a special case (Windows spells it `_hypot`), and that special case
declared it with a **single** parameter:

```rust
return Some(self.insert_intrinsic(name, &[t_f64], t_f64, false));
```

while `mir_llvm/src/builder.rs` emits a two-argument call. Every other binary entry in
the table — `atan2` and `llvm.pow.f64`, both a few lines away — is declared correctly;
`hypot` is the odd one out because it sits outside the `ifn!` macro block.

Constant arguments fold before code generation, so `hypot(3.0, 4.0)` never reached the
bad declaration; only a runtime argument did.

The reason this survived is that the check which reports it — `llmod.verify_and_print()`
in `osdi/src/lib.rs` — is a `debug_assert!`. Release builds never run the module
verifier, so they emitted the malformed call.

## Fix

Declare it binary, matching the call and its neighbour `atan2`:

```rust
return Some(self.insert_intrinsic(name, &[t_f64, t_f64], t_f64, false));
```

## Verification

`examples/vafcodegen_examples/verify_vafcodegen.py` — `hypotclog2.va` uses
`hypot(px, py)` with runtime parameters and checks `hypot(3,4) == 5` exactly (combined
with Enhancement-289's `$clog2(100) == 7`, `I == 12`).

Worth stating plainly: on arm64 macOS the malformed call still produced the **right
number**, because the extra argument lands in the register the callee reads anyway.
This was invalid IR that LLVM is licensed to miscompile — under a different target,
calling convention, or optimization pipeline there is no such guarantee — not a
demonstrated wrong answer on this platform. The authoritative evidence is that the
module verifier now accepts the module.

## Scope

One source file (`openvaf/mir_llvm/src/intrinsics.rs`), one argument list. No public
interface or OSDI ABI change.
