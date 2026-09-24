# Enhancement-489 — `pow` and `**` join the constant-domain guard

```
python3 verify_powguard.py
```

37 checks, a couple of seconds. Of the first eighteen, **12/18** against the
pre-fix compiler — **6** checks discriminate. Checks [19]–[37] are
[Enhancement-706](../../enhancements_doc/Enhancement-706.md)'s (below): **25/37** on
the E-704 binaries, twelve discriminate.

## What it is

Enhancement-455 refuses a **constant** argument outside a function's domain —
`sqrt(-1.0)`, `ln(0.0)`, `asin(2.0)` and four more — because the fold produces a
NaN that reaches the user not as a compiler message but as:

```
Error: Transient op failed, timestep too small
```

a convergence complaint for a NaN written literally in the source.

`pow` was left out of that list. And `pow(-2.0, 0.5)` **is** `sqrt(-2.0)` — the
same operation, the same NaN, the same misleading run-time failure. Measured before
the fix, it compiled clean and produced exactly that message.

## Two spellings, two code paths

`pow(x,y)` resolves to `BuiltIn::pow` and is judged in the call handler. `x ** y`
is `BinaryOp::Power` and never goes near it.

The first version of this fix guarded only the call form — and `(-2.0)**0.5` still
compiled. Judging one spelling of an operation and not the other is exactly how two
siblings drift apart, so both are judged now, on one rule.

## The trap: the integer operation is a *different* operation

`**` on two integers is IEEE 1364-2005 Table 5-6, implemented by
[E-420](../../enhancements_doc/Enhancement-420.md), where a negative exponent is
fully defined:

| | |
|---|---|
| `2 ** -1` | 0 |
| `7 ** -2` | 0 |
| `1 ** -5` | 1 |
| `-1 ** -3` | -1 |
| `0 ** -1` | `'x`, which is 0 in an integer context |

Those are **correct answers, not NaNs**. The first version of this arm judged them
by the real domain rule and rejected valid models — `vafdegen_examples` went from
91/91 to failing ten checks, which is how the mistake was found. The arm now tests
the operand type first.

Checks [7]–[11] hold that line from the other side: they pass on the pre-fix
compiler *and* on the fixed one, and they **fail** against a guard that forgets the
type test.

## Deliberately not guarded

So a later pass does not "extend" this:

* a **run-time** base or exponent — E-455's stated convention, unchanged
* an overridable **`parameter`** — same convention: it may be overridden, so its
  default is not judged. A **`localparam`** *is* judged, because
  [E-479](../../enhancements_doc/Enhancement-479.md) taught `const_num` to see one;
  this guard inherits that for free (checks [5]–[6])
* `pow(-2.0, 3.0)` and `pow(-2.0, -3.0)` — a negative base with an **integer**
  exponent has a real root and is ordinary arithmetic

## Verification

The whole 754-file `.va` corpus was recompiled before and after: **identical
results**, 626 succeeding both times, and **zero** hits of the new diagnostic. Full
ngspice regression 403/403.

## Enhancement-706 — the folder's own NaN and infinity (robustness campaign F6 of 2026-09-23)

The constant-domain guard above judges a constant argument *outside* a function's
domain. Two shapes it did not see: the value the constant folder produces on its own —
`0.0/0.0` folded to NaN in silence, and the NaN then passed every constant-argument
check that refuses `-1`, because `const_num` leaves a zero divisor unfolded for "the
division checks" and the real `/` had none; `1.0/0.0` was not folded at all, so an
infinite delay was "not a constant" to the delay check — and a call *inside* its domain
whose result is past the largest double: `exp(1000.0)`, `cosh(1000.0)`, `pow(10.0,
400.0)`, `10.0 ** 400.0`, all +∞ without a word.

Checks [19]–[37]: `0.0/0.0` is refused at the division ("the operands are both 0, so the
quotient is undefined; the result would be NaN"); `exp(1000.0)`, `cosh(1000.0)`,
`pow(10.0, 400.0)` and `10.0 ** 400.0` are refused as exceeding the largest double,
`exp(700.0)` and `pow(10.0, 300.0)` compile; `1.0/0.0` in an expression and `V(a,b)/0.0`
stay legal (Enhancement-333's contract — IEEE's infinity is a value); `absdelay(V,
1.0/0.0)` and the `localparam`-zero form are refused as "the delay must be a finite
number, but is inf", the overridable-`parameter` form is the deck's business, and
`parameter real q = 1.0/0.0` is Enhancement-640's "overflows to infinity"; `absdelay(V,
1e308*10)` is named finite-not-negative; `absdelay(V, 0.0/0.0)`, a `from [0.0/0.0:1]`
bound and a `'{1, 0.0/0.0}` Laplace denominator are refused before any run time; and
integer `1/0` and `1.0 % 0.0` keep Enhancement-333's and Enhancement-578's sentences.
