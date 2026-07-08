# Enhancement-101 — `$clog2` correctness (arity + value)

A probe sweep over under-exercised Verilog-A constructs (the E-59/E-84
methodology) turned up a two-layer bug in the `$clog2` system function. Both
layers are fixed here.

## What `$clog2` should do

`$clog2(n)` is the IEEE-1800 system function that returns the **ceiling of the
base-2 logarithm** of its single argument — the number of bits needed to index
`n` distinct values. Per the standard, `$clog2(0)` is `0`. So `$clog2(1) = 0`,
`$clog2(16) = 4`, `$clog2(17) = 5`, `$clog2(1024) = 10`.

## The two bugs

**1. Wrong arity — every call rejected.** `$clog2` was aliased to a 2-argument
integer signature (`INT_MATH_2`), so *any* call was rejected at type-check time:

```
error: invalid argument count: expected 2 arguments but found 1
    b = $clog2(W);
        ^^^^^^^^^ expected 2 arguments
```

The builtin id, the lowering (`hir_lower`), and the MIR `Clog2` opcode were all
present and expected a **single** argument — only the `hir_ty` signature table
was wrong. This is the recurring "scaffolded but mis-wired at the signature
table" pattern. The fix adds a 1-arg integer signature `INT_MATH_1` and points
`CLOG2` at it (`openvaf/hir_ty/src/builtin.rs`).

**2. Wrong value — off by one on powers of two.** With the arity fixed, a second
bug surfaced (it had been fully masked, since no call ever compiled): all three
backends computed

```
clog2(n) = 32 - clz(n) = bit_width(n) = floor(log2 n) + 1
```

That is the *bit width* of `n`, which equals `ceil(log2 n)` only when `n` is
**not** a power of two. For exact powers it is one too large:

| n | correct `$clog2` | old result |
|---|---|---|
| 1 | 0 | 1 |
| 16 | 4 | 5 |
| 1024 | 10 | 11 |
| 33 | 6 | 6 ✓ |

The correct identity is `ceil(log2 n) = bit_width(n-1)` for `n ≥ 2`, and `0` for
`n ≤ 1`. The fix applies this in all three places that implement the `Clog2`
opcode:

- `openvaf/mir_interpret/src/lib.rs` (interpreter),
- `openvaf/mir_opt/src/const_eval.rs` (constant folding — the literal path),
- `openvaf/mir_llvm/src/builder.rs` (LLVM codegen — the runtime,
  parameter-dependent path). Here the `ctlz` intrinsic is now emitted with
  `is_zero_poison = false` so that `ctlz(0) = 32` is well defined (making the
  `n = 1` case, where `n-1 = 0`, evaluate to `0`), with a `select` guarding
  `n < 1 → 0`.

## Verification

`clog2_examples` (13/13): `clog2_demo.va` exposes `$clog2` results as
operating-point variables and is read back in ngspice via `.op`. The
constant-folded literals `$clog2(1,2,3,4,7,8,16,17,1024)` and the runtime
parameter path `$clog2(N)` for `N ∈ {16, 33, 1}` all match `ceil(log2 n)`
exactly — in particular the powers-of-two cases that the old code got wrong.

The wider probe battery (~35 constructs: severity tasks `$info`/`$warning`/
`$error`, `ddx`, `$limit`, `hypot`/`atan2`/`limexp`, `aliasparam`, `timer`/
`cross`/`above` events, named-block `disable`, switch branches, `$temperature`/
`$vt`, analog-function recursion, …) otherwise compiled or produced the correct
diagnostic — `$clog2` was the one real defect found. Full regression: all verify
suites plus the OpenVAF integration tests remain green.
