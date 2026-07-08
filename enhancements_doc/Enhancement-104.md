# Enhancement-104 — `$rtoi` / `$itor` real↔integer conversion functions

A second, wider gap-hunt round (static-value + dynamic transient batteries)
confirmed the math builtins, integer/bit operators, and the time-domain
operators (`ddt`, `idt`, `absdelay`) all return correct values. What it *did*
surface is a missing pair of standard conversion functions.

## The gap

Verilog / Verilog-AMS provides two explicit conversion system functions:

- **`$rtoi(real)` → integer**, converting by **truncating toward zero**;
- **`$itor(integer)` → real**.

openvaf-r supported the *implicit* conversions (assigning a real to an integer
variable, and vice versa), but the explicit functions were unknown:

```
error: '$rtoi' was not found in the current scope
```

They matter because `$rtoi` is **not** interchangeable with the implicit cast:
an implicit real→integer assignment **rounds** to nearest, whereas `$rtoi`
**truncates**. So `$rtoi(3.9)` is `3` (not `4`) and `$rtoi(-3.9)` is `-3` (not
`-4`). Compact models that want truncation had no correct way to express it.

## The implementation

Two new builtins wired through the standard path — the interned names
(`syntax/src/name.rs`), the `BuiltIn` enum + scope registration
(`hir_def/src/builtin.rs`), the type signatures (`hir_ty`), and the MIR
lowering (`hir_lower/src/expr.rs`):

- **`$itor`** lowers to the existing integer→real cast (`ifcast`) — exact.
- **`$rtoi`** must truncate toward zero, which the rounding `FIcast` cast does
  not do. It lowers to `ficast( (x < 0) ? ceil(x) : floor(x) )`: `floor`/`ceil`
  select the toward-zero neighbor, producing an exact integer-valued real that
  the final cast carries through unchanged. This reuses only existing MIR ops,
  so both the runtime (LLVM) and the constant-folding paths compute it.

## Verification

`convert_examples` (9/9): `convert_demo.va` takes `$rtoi` of module parameters
(the runtime path) and of a `localparam` (the constant-folding path), and
`$itor` of an integer. It checks the toward-zero truncation on positive and
negative inputs — `$rtoi(3.9)=3`, `$rtoi(-3.9)=-3`, `$rtoi(-3.2)=-3`,
`$rtoi(5.0)=5` (a rounding cast would give `4`/`-4`), that `$rtoi(9.6)` in a
`localparam` const-folds to `9`, and that `$itor(7)*0.5 = 3.5` (proving `$itor`
yields a real, not an integer). The gap-hunt batteries behind this enhancement
(static values across trig / conversion / based literals, and a transient
`ddt`/`idt`/`absdelay` battery) otherwise matched their analytic values
exactly. Full regression: all verify suites plus the OpenVAF integration tests
remain green.
