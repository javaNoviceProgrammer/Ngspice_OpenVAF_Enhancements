# Enhancement-664: the compile-time constant folder divides two integers as integers — L030 no longer calls `7/2` "the default 3.5", and L027 judges the value the model runs with

**Scope:** F5 of the
[bug hunt of 2026-09-18](../docs/bug_hunts/2026-09-18_openvaf-r-corners-and-run-control.md).
Compiler: `openvaf/hir_ty/src/validation/body.rs` (`const_num_in`: LRM 4.2
integer division; `is_integer_typed`). `examples/hunt3diag_examples/` (three
checks added, 45 per solver). Handbook
[§2.4](../docs/handbook/02-verilog-a-language.md) row. **Compiler only.**

**Suites:** [`hunt3diag_examples`](../examples/hunt3diag_examples/) 45 of 45
per solver, both solvers (two of the three new checks fail on the E-661
compiler); `paramrange` unchanged; the compiler's workspace tests green (the
three sourcegen rewrites are the known drift); full sweep 529 of 529.

## What was wrong

```
parameter integer a = 7/2;      warning[L030]: ... has the default 3.5, which an integer cannot hold
parameter integer b = -7/2;     ... the default -3.5 ...                    (the model runs with -3)
parameter integer c = 3*2/4;    ... the default 1.5 ...                     (1)
```

LRM 4.2: *integer division truncates any fractional part toward zero*, and the
compiled model does so — `$strobe` prints 3, −3, 1. The compile-time constant
folder behind the diagnostics, `const_num_in` ([E-590](Enhancement-590.md)),
folded `/` on two integers as a real division, so L030 complained about a value
the parameter never holds, and — the part that is not merely a wrong message —
L027's range judgement and every other consumer of a folded default saw the
wrong number: `parameter integer d = 7/2*2 from [0:6]` was judged 7 against its
range where the model runs with 6, and `7/2 from (3:9]` was judged 3.5, inside,
where the model's 3 is outside. `param_default_const`, which the corner
attribute's zero-default check and the paramset selection read, folds through
the same function.

## What changed

`const_num_in` truncates the quotient toward zero when the inference types both
operands as integers — an integer literal, an integer parameter or variable, or
an integer-typed subexpression, so `7/2*2` folds to 6 and `9/4/2` to 1. A real
operand keeps the real division: `7.0/2` is still 3.5 and still L030 (the model
rounds it to 4), and `parameter real r = 7/2` folds to 3, which is what the
model computes. A zero divisor is still left to the division checks.

## Verification

| check | result |
|---|---|
| `integer q = 7/2`, `m = -7/2`, `d = 7/2*2 from [0:6]` | no L030, no L027 |
| `integer k = 7/2 from (3:9]` | L027: the default 3 violates its range (was silent at 3.5) |
| `integer e = 7.0/2` | L030, the default 3.5, rounded to 4 (as before) |
| the model at run time | `q=3 m=-3 d=6 k=3 e=4 r=3` |
| the E-661 compiler on the same suite | the two diagnostic checks fail |

Full sweep 529 of 529 on both solvers.

## What this does not do

- `%` and `**` are not folded by this function, as before; the hunt found them
  reported right because they are not reported at all.
- Integer overflow in a folded `+`, `-` or `*` is not wrapped: the folded value
  is exact and L030 reports it as overflowing, which is what the literal check
  does too.
- `parameter real r = 7/2` giving 3 is the LRM's rule, not a defect; a lint for
  an integer division feeding a real parameter would be a separate enhancement.
