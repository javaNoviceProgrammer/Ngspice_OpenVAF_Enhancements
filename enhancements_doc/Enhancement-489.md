# Enhancement-489 — `pow` and `**` join the constant-domain guard

**Files:** `openvaf/hir_ty/src/validation/body.rs`, `openvaf/hir_lower/src/expr.rs`
(comment only).

**Suite:** `examples/powguard_examples/` — 18 checks.

## Why

Enhancement-455 refuses a **constant** argument outside a function's domain and
says exactly why in its own comment:

> *"`sqrt(-1.0)`, `ln(-1.0)`, `asin(2.0)` and friends folded to NaN with no
> diagnostic at all, and the model then failed at simulation with "Transient op
> failed, timestep too small" -- a convergence message for a NaN written literally
> in the source."*

It guards `sqrt | ln | log | asin | acos | acosh | atanh`. **`pow` is not in that
list**, and `pow(-2.0, 0.5)` *is* `sqrt(-2.0)` — a negative base with a fractional
exponent has no real root. Measured before this change, it compiled clean and the
model then failed with precisely the message E-455 exists to prevent.

A second constant shape has no value either: a zero base with a negative exponent
is a division by zero, and is infinite.

## Two spellings, two code paths

`pow(x,y)` resolves to `BuiltIn::pow` and is judged in the call handler.
`x ** y` is `BinaryOp::Power` and never reaches it.

The first version of this fix added only the call arm — and `(-2.0)**0.5` still
compiled. Judging one spelling of an operation and not the other is the drift this
project keeps having to undo, so a second arm judges the operator form in
`validate_expr` on the identical rule.

Both inherit Enhancement-479's `const_num` for free, so a `localparam` base or
exponent is seen exactly as a literal is.

## The trap: the integer `**` is a different operation

This is the part worth recording, because the first attempt got it wrong and a
committed suite caught it.

`**` on two **integers** is IEEE 1364-2005 Table 5-6, implemented by
Enhancement-420, and a negative exponent there is fully defined — `2 ** -1` is 0,
`7 ** -2` is 0, `1 ** -5` is 1, `-1 ** -3` is -1, and a base of 0 is `'x`, which
E-420's own comment notes "is 0 in an integer context — the same answer the
`otherwise` arm already gives".

Those are correct answers, not NaNs. The first version of the operator arm judged
them by the **real** domain rule and rejected valid models: `vafdegen_examples`
went from 91/91 to failing ten checks, all of the form

```
error: **: the base is 0 with the negative exponent -1
```

The arm now returns immediately when the expression's inferred type is `Integer`.
Checks [7]–[11] of the new suite hold that line from the other side — they pass on
the pre-fix compiler *and* the fixed one, and fail against a guard that forgets the
type test.

## What this deliberately does not change

* A **run-time** base or exponent is untouched. That is E-455's stated convention:
  *"a run-time value going out of domain is the model's own business."*
* An overridable **`parameter`** is untouched, for the same reason — it may be
  overridden, so its default is not judged.
* `pow(-2.0, 3.0)` and `pow(-2.0, -3.0)` still compile: a negative base with an
  **integer** exponent has a real root and is ordinary arithmetic.

## Two findings from the same hunt that were withdrawn rather than fixed

Both were withdrawn on evidence in the source, and both are recorded here so they
are not re-reported:

* **Real `/0` and `%0` are unguarded while the integer forms are compile errors.**
  The premise was wrong. `inference.rs` (Enhancement-333) states that the integer
  guard exists because *"LLVM treats `sdiv x, 0` as immediate undefined behaviour
  and lowers it to poison → `unreachable` → a `brk`, so the compiled .osdi killed
  the host simulator with SIGTRAP"*, and is scoped *"LITERAL only, which is exactly
  the UB surface"*. Floating-point `fdiv x, 0.0` is well-defined IEEE — no poison,
  no trap, no UB. The two are guarded for different reasons and the integer
  rationale does not transfer.
* **A dynamic array index out of range silently yields element 0.** The
  compile-time story is already complete: a literal, a localparam *and* a derived
  constant index are all rejected. Only an overridable parameter reaches the select
  chain, and that is a run-time value under the same convention as above. Seeding
  the chain with NaN to make it loud was considered and rejected: the same lowering
  serves **variable** indices, where an index can be transiently out of range
  mid-solve, so a NaN would poison the iteration and break models that converge
  today. What the site lacked was a statement that the `elems[0]` fallback is
  intended; that is now written there, including why NaN was rejected.

## Verification

```
python3 examples/powguard_examples/verify_powguard.py    # 18/18
python3 examples/vafdegen_examples/verify_vafdegen.py    # 91/91
python3 examples/run_regression.py                       # 403/403
```

**12/18** against the pre-fix compiler, so **6 of 18 checks discriminate**; the
other twelve are controls that must not move, and do not.

The whole **754-file `.va` corpus** was recompiled before and after the change:
results byte-identical, 626 succeeding both times, and **zero** occurrences of the
new diagnostic anywhere. The 128 non-compiling files are pre-existing — compiler
test fixtures and include-only macro banks compiled standalone.
