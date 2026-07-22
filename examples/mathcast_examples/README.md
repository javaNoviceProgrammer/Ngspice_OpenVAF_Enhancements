# mathcast_examples — Enhancement-273

Several `cmath2.c` expression routines converted a `double` operand to `int` with a
plain cast, which is undefined behaviour for a non-finite or out-of-range value:

- **`cx_mod` (the `%` operator)** — `1e30 % 5` tripped UBSan and, on the shipped
  build, returned a garbage `2` instead of erroring;
- **`cx_vector` / `cx_cvector` / `cx_unitvec`** — `vector(1e30)` / `unitvec(1e30)`
  saturated the length to ~`INT_MAX`, then allocated and filled it: a multi-GB
  `calloc` (macOS over-commit) plus a billion-iteration loop — an apparent **hang**
  on the shipped build, not just under a sanitizer.

Fix (`src/maths/cmaths/cmath2.c`): range-check before every `(int)` cast. `%`
rejects an out-of-range operand with the existing `argument out of range for mod`
error; the vector builders reject a non-representable length via a shared
`cx_veclen()` helper (`vector length ... is out of range`). Valid expressions are
unchanged.

## Verify

```
python3 verify_mathcast.py
```

Five checks: `1e30 % 5`, `vector(1e30)`, and `unitvec(1e30)` each error cleanly and
fast; valid `17 % 5` (= 2) and `vector(4)` (= [0,1,2,3]) still evaluate correctly.
