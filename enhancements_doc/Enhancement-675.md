# Enhancement-675: L030 says what an integer default becomes — an integer expression that overflows wraps, and the lint said "clipped"

**Scope:** F3 of the
[bug hunt of 2026-09-19](../docs/bug_hunts/2026-09-19_openvaf-r-operators-folding-and-delays.md).
openvaf: `hir_ty/src/validation/body.rs` (`const_int_wrapping`, the 32-bit
twin of `const_num_in`; `int_pow_exact`; `**` on two integers folded; the
L030 check and the range check judge the stored value),
`hir_ty/src/validation.rs` (the message, the label and the note).
`examples/hunt3diag_examples/` (six checks added, 51 per solver). Handbook
[§2.4](../docs/handbook/02-verilog-a-language.md) row. **openvaf only.**

**Suites:** [`hunt3diag_examples`](../examples/hunt3diag_examples/) 51 of 51
per solver, both solvers (5 of the 6 new checks fail on the E-670 binaries;
the run-time strobe is the same on both, the model always wrapped); the
compiler workspace tests green apart from the three pre-existing sourcegen
drift failures; full sweep 531 of 531.

## What was wrong

| `parameter integer p =` | L030 said | the model card showed |
|---|---|---|
| `1e10` | clipped to 2147483647 | 2147483647 |
| `2147483647 + 1` | clipped to 2147483647 | **−2147483648** |
| `100000 * 100000` | clipped to 2147483647 | **1410065408** |
| `-2147483647 - 2` | clipped to −2147483648 | **2147483647** |
| `2147483647 * 2` | clipped to 2147483647 | **−2** |
| `2 ** 31` | (nothing) | 2147483647 |

[E-590](Enhancement-590.md)'s check evaluated the default with
`const_num_in`, as a real, and when the value lay outside 32 bits wrote
"clipped to" the nearer bound. That is what happens to a *real* value: the
conversion that stores it saturates (the literal `3000000000` is read as a
real, which is E-590's own case). An integer-typed expression is computed by
the model — and by the MIR folder, [E-286](Enhancement-286.md) — in 32-bit
two's-complement arithmetic, which wraps, so four of the rows named a value
the parameter never takes. `2 ** 31` drew no warning because the folder had
no `**`. And the range check judged the exact value: `2147483647 + 1 from
[-2147483648:0]` was warned as violating its range while the model ran with
−2147483648, inside it.

## What changed

**The lint computes the default the way the model does.** `const_int_wrapping`
is `const_num_in`'s 32-bit twin for an integer-typed expression: `+`, `-`,
`*` wrap; `/` and `%` truncate (a zero divisor and `i32::MIN / -1` are left
to their own diagnostics); `**` follows `lower_int_pow` — IEEE 1364-2005
Table 5-6 for a negative exponent, the rounded float power through the
saturating cast otherwise; a `localparam` chain is followed. Anything else —
a shift, a call — is not folded, and the exact value stands as before.

The warning fires when the exact value has a fraction, does not fit, **or
differs from the stored one**: an intermediate overflow can land on a value
that fits (`(2147483647 + 1) / 2` is 1073741824 exactly and −1073741824 in
the model), and that case gets its own sentence. The label says "wraps to
N"; for the saturating power it says "clipped to N", which is then true.
The note names the rule (32-bit two's complement, LRM 3.2's range) and keeps
E-590's reminder that a model card refuses the same value. `const_num_in`
folds `**` on two integers, exactly, so `2 ** 31` is judged; a real `**`
stays unfolded. The range check judges the stored value, as it has judged
the truncated quotient since [E-664](Enhancement-664.md).

## Verification

| check | result |
|---|---|
| `2147483647 + 1`; `100000 * 100000`; `-2147483647 - 2`; `2147483647 * 2` | wraps to −2147483648; 1410065408; 2147483647; −2 — the model card's values (was "clipped to" a bound) |
| `2 ** 31` | clipped to 2147483647 (was no warning) |
| `big + 1` with `localparam integer big = 2147483647` | wraps to −2147483648 |
| `(2147483647 + 1) / 2` | "has the default 1073741824 in exact arithmetic, which its 32-bit integer arithmetic does not reach", wraps to −1073741824 |
| `1e10` | clipped to 2147483647 (unchanged: a real value) |
| `2147483647 + 1 from [-2147483648:0]` | no L027 (was L027, the exact value judged) |
| `7 ** 2`, `2 ** -1`, `(-1) ** 3` | 49, 0, −1; no warning |
| the model at run time | every value as its label says |
| the E-670 binaries on the suite | 5 of the 6 new checks fail (the run-time values agree) |
| workspace tests; full sweep | green apart from the sourcegen drift; 531 of 531 |

## What this does not do

- The integer `**` still saturates where every other integer operator wraps
  (the 2026-09-04 compiler hunt's F5, open); the lint mirrors what the model
  does, it does not change it.
- E-590's literal rule stands: `3000000000` is read as a real, so
  `3000000000 - 1` is real arithmetic and *clips*, and the literal's own L030
  says so.
- A default with a shift or a bitwise operator is folded by neither
  evaluator and is not judged, as before.
