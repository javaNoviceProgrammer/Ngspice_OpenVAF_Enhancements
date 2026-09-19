# Enhancement-674: `pow(0.0, x)` is no longer folded to 0 — the simplifier's zero-base rule gave 0 at x = 0 and for a negative exponent

**Scope:** F2 of the
[bug hunt of 2026-09-19](../docs/bug_hunts/2026-09-19_openvaf-r-operators-folding-and-delays.md).
openvaf: `mir_opt/src/simplify.rs` (`simplify_pow_inst`, the zero-base rule
removed). `examples/mathident_examples/` (six checks added, 18). **openvaf
only.**

**Suites:** [`mathident_examples`](../examples/mathident_examples/) 18 of 18
(3 of the 6 new checks fail on the E-670 binaries: the value at x = 0 in both
spellings and at x = −1); the compiler workspace tests green apart from the
three pre-existing sourcegen drift failures; full sweep 531 of 531.

## What was wrong

The MIR simplifier's `pow` rules ran in this order: `pow(x, 0.0) → 1`, then
the constant-constant fold, then **`pow(0.0, x) → 0`**, then `pow(x, 1.0) → x`.
The third is right only for x > 0:

| `pow(0.0, V(a,b))` at V | was | is (C's `pow`) |
|---|---|---|
| −1 | 0 | +inf |
| 0 | 0 | **1** |
| 1 | 0 | 0 |
| NaN | 0 | NaN |

`pow(0.0, 0.0)` written out folded to 1 through the first rule, so the two
spellings of the same call disagreed; `0.0 ** x` is the same instruction. A
*parameter* base of 0 is a run-time value and was never folded: it takes
[E-509](Enhancement-509.md)'s run-time domain `$fatal` for a negative
exponent and gives 1 at zero. `ddx(pow(0.0, x), V(a))` folded to 0 with the
value.

## What changed

**The zero-base rule is gone.** The exponent's sign is not known at fold
time, so there is no simplification of a literal-zero base; the call stays
and the value is the library's. `pow(x, 0.0) = 1` (C's rule, for every x
including NaN) and `pow(x, 1.0) = x` hold for every x and stay, as does the
constant-constant fold. The derivative now follows the autodiff builder's
guarded form (`pow(a, x)·ln(a)` with a = 1e-18 at a zero base), the same
value `ddx(pow(|x|, x), V(a))` already reads at zero.

## Verification

| check | result |
|---|---|
| `I(a,b) <+ 1e-3*pow(0.0, V(a,b))` at V = 0 | 1e-3 (was −0) |
| the same at V = 1 | 0 (unchanged) |
| `1e-3*(0.0 ** V(a,b))` at V = 0 | 1e-3 (was −0) |
| `pow(0.0, V(a,b))` as an operating-point variable at V = −1 | +inf (was 0) |
| `pow(V(a,b), 0.0)` at V = −3; `pow(V(a,b), 1.0)` at V = −3 | 1; −3 (the rules that stay) |
| the hunt's `ddx(pow(0.0, x), V(a))` probe | the guarded derivative, no longer a folded 0 |
| the E-670 binaries on the suite | 3 of the 6 new checks fail (the two x = 0 values, the −1 exponent) |
| workspace tests; full sweep | green apart from the sourcegen drift; 531 of 531 |

## What this does not do

- `0.0 * x → 0` and `0.0 / x → 0` still fold, hiding a NaN or an infinite
  `x` (IEEE gives NaN); `x - x` and `x / x` are not folded. That is the usual
  fast-math trade and is recorded in the hunt's smaller notes, not changed here.
- A solution-dependent exponent still gets no run-time domain check
  ([E-509](Enhancement-509.md)/[E-651](Enhancement-651.md)'s rule): `pow(0.0,
  V)` with V < 0 is +inf and the Newton solve fails on it, which is the
  model's own.
