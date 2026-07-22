# Enhancement-281 — ngspice: `deriv()` over-read on a partial block (grouping ≠ length)

The expression fuzz flagged `cmath4.c` on `deriv(min(v(b), ac.v(b)))` — a derivative of
a binary op whose operands had different lengths.

## The bug

`cx_deriv` walks its input in blocks:

```c
for (base = 0; base < length; base += grouping)
    for (i = degree; i < grouping; i += 1)
        ... fit window around  i + base ...
```

`grouping` is the vector's `v_dims[0]`. For an ordinary vector that equals `v_length`,
so there is a single block and the window always fits. But a vector whose declared
dimension differs from its length — as produced by a binary op on operands of unequal
length, e.g. `min(v(b), ac.v(b))` where a 66-point real and a 5-point complex vector
yield length 66 with `dims[0] = 5` — leaves a **partial last block**: `base` climbs to
`length - 1` while the window still spans `base + grouping - 1`, reading past the end
of the input (AddressSanitizer heap-buffer-overflow READ).

## Fix

`src/maths/cmaths/cmath4.c`: bound the inner loop with `i + base < length` in both the
real and complex branches, so the fit window can never reach past the input. This is a
no-op whenever `grouping == length` — i.e. for every ordinary vector — and a partial
trailing block (too short to hold a full window) is simply skipped.

## Verification

`examples/derivgroup_examples/verify_derivgroup.py` (4 checks):
`deriv(min(v(b), ac.v(b)))` and `deriv(max(v(b), ac.v(b)))` are clean where they
previously over-read; an ordinary real `deriv(2t)` still returns `2`; and the complex
derivative from Enhancement-277 is still correct (`deriv(t + 2t·i) = 1 + 2i`).

## Scope

One source file (`src/maths/cmaths/cmath4.c`), a loop bound in each branch. No change
to any ordinary derivative.
