# Enhancement-103 — `ceil()` of a runtime argument (missing LLVM intrinsic)

A wider probe sweep (the E-101 methodology, extended with a runtime-value
battery) turned up a compiler **crash**: `ceil()` applied to any non-constant
argument aborts code generation.

## The bug

The LLVM code generator lowers `ceil(x)` to the `llvm.ceil.f64` intrinsic, but
that intrinsic was never registered in the compiler's intrinsic table
(`openvaf/mir_llvm/src/intrinsics.rs`). When codegen asked for it, the lookup
returned `None` and the compiler panicked:

```
internal error: entered unreachable code: intrinsic llvm.ceil.f64 not found
```

Its sibling `llvm.floor.f64` *was* registered, so `floor(x)` compiled fine — a
textbook "scaffolded but unwired" gap. The crash was fully masked whenever the
argument was a compile-time constant (`ceil(2.1)`), because that folds to a
value long before codegen; it only fired for a genuinely runtime argument, e.g.
`ceil` of a parameter or a node voltage:

```verilog
parameter real a = 2.1;
real y;
analog y = ceil(a);   // crashed the compiler (llvm.ceil.f64 not found)
```

## The fix

One line — register the missing intrinsic next to `floor`:

```rust
ifn!("llvm.floor.f64", fn(t_f64) -> t_f64);
ifn!("llvm.ceil.f64",  fn(t_f64) -> t_f64);   // Enhancement-103
```

An audit of every intrinsic name requested by the code generator against the
registered table confirmed `llvm.ceil.f64` was the *only* missing one — all
other math builtins (`sqrt`, `exp`, `ln`, `log10`, `pow`, `sin`/`cos`/`tan`,
the hyperbolic and inverse-hyperbolic family, `hypot`, `atan2`, `fabs`,
`ctlz`, `lround`) resolve.

## Verification

`ceil_examples` (8/8): `ceil_demo.va` takes `ceil` of module parameters (the
runtime path that used to crash) and reads the results back in ngspice —
`ceil(2.1)=3`, `ceil(2.0)=2`, `ceil(-2.7)=-2`, `ceil(-0.5)=0`, `ceil(5.0)=5`,
with `floor` cross-checked on the same inputs. The wider runtime-value battery
behind this enhancement (37 math / integer / bit expressions checked against
analytic values) otherwise matched exactly — `ceil` was the one real defect
found. Full regression: all verify suites plus the OpenVAF integration tests
remain green.
