# `idt` initial-condition in a dead branch (Enhancement-317)

Found by grammar-based analog-operator fuzzing (the [E-307](../../enhancements_doc/Enhancement-307.md)–[E-314](../../enhancements_doc/Enhancement-314.md) family). An `idt()`
with an initial condition placed inside a statically-false branch crashed the shipped compiler.

`ceil(0) > 1` is always false but `ceil()` is not const-folded, so the dead branch survives into
MIR. The guarded `w = idt(V(a),0)` initial-condition state is never used, so codegen prunes the
branch *condition's* computation as dead — yet the `Branch` instruction survives into
`osdi::setup::setup_instance`, and reading its now-`Undef` condition hit `unreachable!()` in the
LLVM builder (`mir_llvm/builder.rs:143`), crashing the compiler (exit 101). Same `Undef`-value
class as [E-308](../../enhancements_doc/Enhancement-308.md) (which handled the *phi-input* case);
this is the *branch-condition* case. Fixed by lowering an `Undef` branch condition as constant
`false` (the guarded code is dead either way) — verified corpus-bit-identical.

## Verify

```sh
python3 verify_vafidtcfg.py
```

Two checks under both solvers: the reproducer compiles (it crashed the shipped compiler before),
and its model simulates to a finite operating point (i(v1) = −5e-4).
