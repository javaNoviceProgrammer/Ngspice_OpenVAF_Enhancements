# rndcast_examples — Enhancement-276

`cx_rnd` (the `rnd()` function, `src/maths/cmaths/cmath2.c`) built a modulus with
`(int) floor(operand)`. Casting a `double` outside int range to `int` is undefined
behaviour, so `rnd(1e30)` (or inf/NaN) tripped UBSan -- the same class as
Enhancement-273, which had not covered `cx_rnd`.

Fix: a `cx_rnd_i()` helper clamps the value to int range (NaN -> 0) before the cast
(real operand + real/imag parts of a complex operand). In-range operands are unchanged.

## Verify

```
python3 verify_rndcast.py
```

Three checks: `rnd(1e30)` and `rnd(inf)` resolve cleanly; a valid `rnd(5)` is in [0,5).
