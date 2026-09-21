# Enhancement-693: an integer `**` wraps like every other integer operator — the float power's saturating cast made `x ** 2` differ from `x * x` past 46340

**Scope:** F3 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_openvaf-r-cli-integers-transition-and-json.md).
openvaf: `hir_lower/src/expr.rs` (`lower_int_pow`: the non-negative arm is
exponentiation by squaring in wrapping i32 — `lower_int_pow_const` for a
constant exponent, `lower_int_pow_unrolled` for a run-time one),
`hir_ty/src/validation/body.rs` (`int_pow_wrapping`, the `**` arm of
`const_int_wrapping`, the L030 verdict), `mir_interpret/src/lib.rs`
(`Iadd`/`Isub`/`Imul` wrap in the interpreter too).
`examples/hunt3diag_examples/` (three checks added, two updated; 54 per
solver). Handbook [§2.4](../docs/handbook/02-verilog-a-language.md) row.
**openvaf only.**

**Suites:** [`hunt3diag_examples`](../examples/hunt3diag_examples/) 54 of 54
per solver, both solvers (5 fail on the E-692 binaries: the two `2 ** 31`
expectations and the three new checks); `powguard` 18 of 18, `vafintub` 7 of 7,
`vafdivzero` 5 of 5, `commaexpr` 41 of 41, `vafdegen` 91 of 91, `mathident`
18 of 18, `vafcodegen`, `vafconstlit`, `hunt17diag`, `dropguard` both solvers,
all unchanged; the compiler workspace tests green apart from the three
pre-existing sourcegen drift failures; full sweep 531 of 531.

## What was wrong

With `parameter integer k = 1`, so that nothing folds:

| expression | was | the same value by multiplication |
|---|---|---|
| `(2*k) ** 31` | 2147483647 | `2*2*…*2` (31 times): **−2147483648** |
| `(46341*k) ** 2` | 2147483647 | `(46341*k) * (46341*k)`: **−2147479015** |
| `(3*k) ** 20` | 2147483647 | −808182895 |
| `(2*k) ** 40` | 2147483647 | 0 |

`x ** 2` and `x * x` disagreed for every |x| > 46340, from source that compiled
clean. The folded defaults agreed with the run time (`2 ** 31` stored
2147483647), and L030 described both honestly and contradictorily: "clipped
to 2147483647" for `2 ** 31`, "wraps to −2147483648" for the same value
written as a product.

[E-420](Enhancement-420.md) made `**` on two integers an integer operation
(IEEE 1364-2005 Table 5-6 for a negative exponent), but its non-negative arm
kept the old float path: both operands cast to real, `llvm.pow.f64`, and the
result brought back through `ficast` — the *saturating* real-to-integer
conversion that is right for `$rtoi` and an implicit real assignment
([E-392](Enhancement-392.md)) and wrong for an operator whose operands never
left the integer domain. IEEE 1364-2005 5.4.1 gives `**` the width of its
operands (32 bits for `integer`) and 4.2.1 makes that arithmetic two's
complement, so an overflowing power wraps like an overflowing product — the
rule the generated code, the folder ([E-286](Enhancement-286.md)) and, since
[E-675](Enhancement-675.md), the lint apply to `+`, `-`, `*` and `<<`. E-675
listed the saturating power as the one thing it did not change (the
2026-09-04 hunt's F5); this closes it.

## What changed

**The integer power is integer arithmetic.** `lower_int_pow`'s non-negative arm
is exponentiation by squaring in wrapping `Imul` (plain `mul` in LLVM, the
wrapping fold of E-286). When the exponent is a constant — `x ** 2`, `x ** 3`,
the overwhelmingly common spelling — `lower_int_pow_const` emits the minimal
square-and-multiply chain, so `x ** 2` is literally the one instruction
`x * x` and `x ** 3` is two multiplies. When the exponent is a run-time value,
`lower_int_pow_unrolled` emits the 31-bit chain, unrolled and branchless: bit i
of the exponent (a logical shift and a mask) selects the factor `1 + bit·(p − 1)`
— `p` when set, 1 when clear — and `p` is squared between bits; bit 31 is the
sign, always 0 for the non-negative exponent this arm receives. The
negative-exponent arm (Table 5-6) is unchanged, and the exponent it forces to 0
now feeds a chain that yields 1, which the arm's own 0/1 factor discards. The
float path and its cast are gone from the integer operator.

**The lint's twin follows.** `int_pow_wrapping` is Table 5-6 for a negative
exponent and `i32::wrapping_pow` otherwise; `const_int_wrapping`'s `**` arm uses
it instead of the exact power through a saturating `as`, so L030 says "wraps to
−2147483648" for `2 ** 31` and "wraps to −2147479015" for `46341 ** 2` — the
same label the product spelling gets — and the "clipped" special case for the
power is removed. `int_pow_exact` stays for the exact value a message quotes.

**The MIR interpreter wraps.** Its `Iadd`, `Isub` and `Imul` were Rust's checked
operators, which panic on overflow in a debug build where the model wraps;
they are `wrapping_*` now, as the generated code and the folder already were.

## Verification

| check | result |
|---|---|
| `(2*k) ** 31`, `(2*k) ** (31*k)` (constant and run-time exponent) | −2147483648 (was 2147483647) |
| `(46341*k) ** 2`, `(46341*k) ** (2*k)` against `(46341*k) * (46341*k)` | −2147479015, all three (was 2147483647 for the powers) |
| `(3*k) ** (20*k)`; `(2*k) ** 40`; `(-2*k) ** (31*k)` | −808182895; 0; −2147483648 |
| `(7*k) ** 11` (no overflow) | 1977326743, exact |
| `(2*k) ** (-1*k)`, `(-1*k) ** (3*k)`, `(0*k) ** (0*k)` (Table 5-6) | 0, −1, 1, unchanged |
| the folded defaults `2 ** 31`, `46341 ** 2`, `3 ** 20` | −2147483648, −2147479015, −808182895, matching the run time |
| L030 for those defaults | "wraps to …" with the same three values (was "clipped to 2147483647") |
| the fourteen values at `-O 0` against `-O 3` | identical |
| the hunt's `p3.py`/`p6.py` modules at `-O 0` against `-O 3` | identical |
| the E-692 binaries on the suite | 5 of 54 fail per solver (the two `2 ** 31` expectations, the three new checks) |
| workspace tests; full sweep | green apart from the sourcegen drift; 531 of 531 |

## What this does not do

- `$rtoi` and the implicit real-to-integer conversion still saturate: that is
  the conversion's rule ([E-392](Enhancement-392.md)), and a real `**` that is
  then stored into an integer goes through it as before. Only the integer
  operator changed.
- A real `**` (`pow`) is untouched, including [E-674](Enhancement-674.md)'s
  folding rules.
- The run-time-exponent chain is 31 unrolled steps (about 190 integer
  instructions); a constant exponent, the common case, costs one multiply per
  bit. Neither is measurable against the surrounding model, and the folder
  collapses both when the base is constant too.
- Overflow is not diagnosed at run time — wrapping is the LRM's arithmetic,
  not an error; L030 names it for a constant default, as E-675 arranged.
