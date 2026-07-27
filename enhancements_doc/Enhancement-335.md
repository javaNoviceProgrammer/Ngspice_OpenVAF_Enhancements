# Enhancement-335 — IEEE 754 and IEEE 1364 semantics the compiler was not honouring

Three independent wrong answers on ordinary code. None crashed; each silently
produced a plausible number instead of the specified one.

## 1. `!=` on reals was an ordered comparison

`Fne` lowered to `LLVMRealONE` — *ordered* not-equal, which is **false** whenever an
operand is NaN. So:

```verilog
q = sqrt(V(w));        // w < 0  ->  NaN
(q != q)               // gave 0; IEEE requires 1
!(q == q)              // gave 1
```

`x != x` is the canonical isnan idiom, and it silently reported "not NaN". Worse,
`a != b` was not the complement of `a == b` — the two disagreed on the same pair of
operands. `Feq` correctly stays **ordered** (`OEQ`, so `NaN == NaN` is false); the two
are complements again only once `Fne` is **unordered** (`UNE`), which it now is.

## 2. An out-of-range shift distance was left to the hardware

A Verilog-A `integer` is 32 bits, so IEEE 1364 requires a shift of 32 or more to
produce 0 (the right operand is treated as unsigned, so a negative distance is a huge
one and also gives 0). openvaf emitted a bare `shl`/`lshr`/`ashr`, and AArch64 masks
the distance to 5 bits:

```verilog
1 << n     // n = 32  ->  gave 1  (i.e. 1 << 0);  Verilog requires 0
(-1) >> n  // n = 32  ->  gave -1;                Verilog requires 0
```

Only the **runtime** form was affected — a literal distance is poison and was fixed
separately in Enhancement-334, so the two spellings disagreed with each other as well
as with the language.

The distance is now range-checked in code generation: `<<` and `>>` select 0 when the
unsigned distance is ≥ 32, and `>>>` clamps to 31, which yields exactly the
all-sign-bits result Verilog specifies. Ordinary shifts are untouched.

## 3. The simplifier applied algebra that IEEE doubles do not obey

`Arithmetic for f64` set `DIV_EXACT` and `HAS_SQRT` to `true`, enabling rewrites whose
own comment described them as "only fast math". With node voltages as operands these
fired at run time:

| expression | gave | IEEE |
|---|---|---|
| `V(z)/V(z)` at z = 0 | 1 | NaN |
| `sqrt(V(w))*sqrt(V(w))` at w = −4 | −4 | NaN |
| `exp(ln(V(w)))` at w = −4 | −4 | NaN |

`x - x → 0`, `x + (-x) → 0`, `x * 0 → 0` and `x / -x → -1` are unsound for the same
reason — with infinities and NaN in the value set they are NaN, not 0 or ∓1.

Each of these is exactly how a compact model guards a domain, so folding them replaced
a deliberate NaN with a plausible wrong number — the most dangerous kind of bug,
because the result looks reasonable.

The identities are now gated on a new `EXACT_ALGEBRA` associated constant: **true** for
`i32`, which really does obey algebra, and **false** for `f64`. Naming the property at
each site makes the intent visible instead of implied by the type.

The same reasoning applies to inverse-function cancellation. The *principal-value*
cases (`asin(sin x)` and friends) had already been excluded; the **domain** and
**overflow** ones had not:

```
exp(ln x)       x < 0    -> NaN, not x       cosh(acosh x)  x < 1 -> NaN, not x
ln(exp x)       large x  -> inf, not x       tanh(atanh x) |x|>=1 -> NaN, not x
sinh(asinh x) / asinh(sinh x)  large x -> inf, not x
log(pow(10,y))  large y  -> inf, not y
```

Only `atanh(tanh x)` survives: `tanh`'s range is (−1, 1), strictly inside `atanh`'s
domain, and it cannot overflow — so that direction genuinely inverts everywhere.

## Verified

- `x != x` is true for NaN, and `!=` is the complement of `==`.
- Runtime `1 << 32` and `(-1) >> 32` are 0; `1 << 3` is 8 and `256 >> 3` is 32.
- `x/x`, `sqrt(x)*sqrt(x)` and `exp(ln x)` are NaN outside their domains.
- **Genuine cancellation is preserved and ordinary arithmetic is not perturbed**:
  `(0.5 + 1e16) - 1e16` is 0 (the value really is lost at that scale, matching a
  reference computation) while `(0.5 + 1e3) - 1e3` is exactly 0.5.

That last check matters because it is where I first went wrong: I initially tested
cancellation with `(-4 + 1e16) - 1e16` and expected 0. The double spacing at 1e16 is 2
and −4 is a multiple of 2, so −4 is the **correct** answer and there was no bug to
find. The expectation was wrong, not the compiler.

## Files

- `OpenVAF-master-20260610/openvaf/mir_llvm/src/builder.rs` — `Fne` as unordered, and
  the range-checked shifts.
- `OpenVAF-master-20260610/openvaf/mir_opt/src/simplify.rs` — `EXACT_ALGEBRA`, and the
  tightened inverse-function table.
- `examples/vafieee_examples/` — all three defects and the untouched cases
  (`verify_vafieee.py`, 6 checks).
