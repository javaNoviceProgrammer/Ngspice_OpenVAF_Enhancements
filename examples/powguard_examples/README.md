# Enhancement-489 — `pow` and `**` join the constant-domain guard

```
python3 verify_powguard.py
```

18 checks, a couple of seconds. **12/18** against the pre-fix compiler — **6**
checks discriminate.

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
