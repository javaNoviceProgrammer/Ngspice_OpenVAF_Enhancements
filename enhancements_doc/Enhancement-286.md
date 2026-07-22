# Enhancement-286 — openvaf-r: constant-folding an integer division by zero killed the compiler

```verilog
analog begin
    q = 5 / 0;      // internal error, no output
end
```

`openvaf-r` exited with an internal error and produced no `.osdi`. A *runtime* zero
divisor has always been accepted — the generated code simply performs the division
and the platform decides what happens — so a literal one being fatal at compile time
is an inconsistency, not a policy.

## Root cause

`mir_opt/const_eval.rs`, `eval_binary` is the constant folder for binary MIR
operations. Its integer arm evaluated every opcode directly:

```rust
Opcode::Idiv => func.dfg.iconst(lhs / rhs),
Opcode::Irem => func.dfg.iconst(lhs % rhs),
```

With `rhs == 0` that division happens **inside the compiler process**, so the
compiler is the thing that dies. `i32::MIN / -1` is the same story (it overflows
rather than dividing by zero).

The neighbouring arms had a quieter version of the same problem. `Iadd`/`Isub`/`Imul`
folded with checked arithmetic, and the shifts folded by an unconstrained distance —
so `i = 2147483647 + 1` and `i = 1 << 40` were also evaluated in a way that does not
match what the generated code computes (LLVM emits plain two's-complement wrapping
arithmetic, and a shift distance outside `0..32` is poison).

This is the `const_eval ≡ codegen` invariant: **the folder must produce exactly what
the runtime path would produce, or decline to fold.**

## Fix

`eval_binary` now returns `Option<Value>` — the convention `eval_unary` already used —
and:

* declines (`None`) for `Idiv`/`Irem` with a zero divisor or `i32::MIN / -1`, and for
  a shift distance outside `0..32`. The instruction stays in the MIR and takes exactly
  the runtime path a non-constant divisor would have taken;
* folds `Iadd`/`Isub`/`Imul` with `wrapping_*`, so the folded value matches the
  generated code and an assertions-enabled build no longer aborts.

The single call site in `mir_opt/simplify.rs` forwards the `Option` instead of
wrapping the old value in `Some`.

## Verification

`examples/vafcodegen_examples/verify_vafcodegen.py` — `constfold.va` exercises `5/0`,
`5%0`, `i32::MIN/-1` and `1<<40` in one module; it compiles, where the pre-fix compiler
exited 101. Behaviour-preserving for every operation that *does* have a well-defined
fold: openvaf-r's own test suite is unchanged (no MIR/OSDI snapshot moved) and the full
dual-solver example regression passes.

## Scope

Two source files (`openvaf/mir_opt/src/const_eval.rs`, `openvaf/mir_opt/src/simplify.rs`).
No public interface, OSDI ABI, or valid-input generated-code change.
