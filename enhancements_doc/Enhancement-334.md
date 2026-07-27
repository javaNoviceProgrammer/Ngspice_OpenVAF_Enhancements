# Enhancement-334 — the two integer-UB shapes Enhancement-333 left behind

E-333 fixed integer division by a constant zero, which compiled with exit 0 and then
killed ngspice with SIGTRAP. It was incomplete. The same trap survived for two more
shapes:

```verilog
if ((-2147483647 - 1) / (-1) > 0 && ione > 0) ...   // i32::MIN / -1  -> SIGTRAP
if ((1 << 40) > 0 && ione > 0) ...                  // shift >= width -> SIGTRAP
```

Both compiled with exit 0 and no diagnostic, and both killed the simulator with
signal 5 and no output.

## How this was missed

Enhancement-286's own comment named **all three** cases:

> a zero divisor -- and i32::MIN / -1, which overflows -- has no value we can fold to
> …
> a shift distance outside 0..32 is poison in LLVM

E-286 declined to fold each of them, which is exactly what leaves the poison in the
IR for the optimiser to turn into `unreachable` → `brk`. E-333 read that comment,
fixed the divisor, and did not check whether the other two it named had the same
consequence. They did — the mechanism is identical, only the operation differs.

The lesson is narrow and worth stating: when a comment enumerates several cases that
share a mechanism, fixing one of them is not evidence about the others.

## The fix

The same check E-333 added, extended to the other two operations, with a diagnostic
each:

```
error: integer division overflows
  = help: the result of `-2147483648 / -1` is 2147483648, which does not fit in a
          32-bit integer; the generated code would trap and take the simulator with it

error: shift distance out of range
  = help: a Verilog-A `integer` is 32 bits, so the shift distance must be 0..=31;
          the generated code would trap and take the simulator with it
```

E-333's check tested for a literal. That is not sufficient here: `i32::MIN` **cannot
be written as an integer literal** — `-2147483648` exceeds `i32::MAX` and promotes to
*real*, making that line a real division rather than the integer overflow E-286
believed it was testing. The overflow is only reachable as `(-2147483647 - 1)`. So the
check now folds constant integer expressions — literals plus `+ - *` over them, with
wrapping arithmetic and a bounded recursion depth — which is exactly the set the code
generator sees as constant.

It remains **constant-operand-only**. A parameter or localparam is lowered as a
runtime value, never becomes a constant operand in the IR, and is therefore not
undefined behaviour; rejecting those would break working models.

## Verified

Every previously trapping shape is now a clean exit 65 — `i32::MIN / -1`, the same
with `%`, `1 << 32`, `1 << 40`, `(-1) >> 32`, `1 << (-1)`, and `1 << (4*8)` (which
requires the constant folding, not just a literal).

Everything legal still compiles: `1 << 31` (the largest legal distance), `1 << 0`, a
runtime shift distance, a parameter or localparam zero divisor, `(-2147483647-1) / 2`,
and ordinary integer division and remainder — and they simulate, `I = V/1k` exactly.

## Corpus impact

Across 480 models, **one** changes accept/reject: `examples/vafcodegen_examples/constfold.va`,
E-286's own example, whose `1 << 40` is now rejected. It was updated (see below), not
suppressed. No real model is affected.

## Enhancement-286's example, again

`constfold.va` kept `1 << 40` to prove the folder does not die on it. That line moved
to `intub.va`, which asserts the diagnostic, and the largest **legal** distance
(`1 << 31`) took its place. Its `-2147483648 / -1` line stays, with a comment
recording that it is a *real* division and never tested the integer overflow it was
written for — the integer case now lives in `intub.va`.

## Still open, and not addressed here

At **runtime** an out-of-range shift distance is silently masked to 5 bits: `1 << n`
with `n = 32` yields **1**, where Verilog requires 0, and the literal spelling now
errors. That is a wrong answer rather than a trap, it needs a code-generation change
rather than a front-end check, and it is left for its own change rather than bundled
into a crash fix.

## Files

- `OpenVAF-master-20260610/openvaf/hir_ty/src/inference.rs` — `const_int_expr` and the
  overflow/shift checks.
- `OpenVAF-master-20260610/openvaf/hir_ty/src/diagnostics.rs` — the two diagnostics.
- `examples/vafintub_examples/` — both shapes are clean errors, and the legal forms
  still compile and simulate (`verify_vafintub.py`, 6 checks).
- `examples/vafcodegen_examples/` — E-286's example updated as described above.
