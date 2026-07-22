# Enhancement-276 — ngspice: `rnd()` guards its `(int)` cast against an out-of-range operand

The expression-layer fuzz flagged `src/maths/cmaths/cmath2.c:162` on `rnd(1e30)`.

## The bug

`cx_rnd` (the `rnd()` random-integer function) turns each operand into a modulus:

```c
j = (int) floor(dd[i]);   d[i] = j ? rand() % j : 0;
```

Casting a `double` outside `int` range to `int` is undefined behaviour, so
`rnd(1e30)` (or an `inf`/`NaN` operand) tripped UBSan. This is the same class as
Enhancement-273, which hardened `cx_mod` and the `cx_vector` builders but not
`cx_rnd` (at the time `rnd(1e30)` did not reproduce; the fuzz found the path).

## Fix

`src/maths/cmaths/cmath2.c`: a helper `cx_rnd_i()` clamps the value to `int` range
(mapping `NaN` to 0) before the cast, applied to all three casts (the real operand
and the real/imag parts of a complex operand). The result is unchanged for any
in-range operand.

## Verification

`examples/rndcast_examples/verify_rndcast.py` (3 checks): `rnd(1e30)` and `rnd(inf)`
resolve cleanly (no UB) where they tripped UBSan; and a valid `rnd(5)` still yields
an integer in `[0,5)`.

## Scope

One source file (`src/maths/cmaths/cmath2.c`). Completes the Enhancement-273
`(int)`-cast hardening for `cx_rnd`.
