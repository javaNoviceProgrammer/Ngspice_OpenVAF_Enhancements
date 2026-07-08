# ceil_examples — `ceil()` of a runtime argument (Enhancement-103)

The LLVM code generator lowers `ceil(x)` to the `llvm.ceil.f64` intrinsic, but
that intrinsic was never registered in the compiler's intrinsic table (its
sibling `llvm.floor.f64` was). So `ceil(x)` for any **non-constant** `x` crashed
the compiler (`intrinsic llvm.ceil.f64 not found`), while `floor(x)` compiled
fine. A constant argument (`ceil(2.1)`) folds before codegen and never hit the
bug — only a runtime argument (a parameter or node voltage) did. Enhancement-103
registers the missing intrinsic.

`ceil_demo.va` takes `ceil` of module parameters (the runtime path) and reads
the results back in ngspice: `ceil(2.1)=3`, `ceil(2.0)=2`, `ceil(-2.7)=-2`,
`ceil(-0.5)=0`, `ceil(5.0)=5`, with `floor` cross-checked on the same inputs.
Run: `python3 verify_ceil.py` (8 checks).
