# castguard_examples — Enhancement-279

A systematic audit (grep every `(int) floor/fabs(...)` of a runtime double, plus every
cmaths routine taking a `struct plot *`) found the tail of two classes fixed elsewhere,
at sites the fuzzer had not reached:

- unguarded `(int) floor(x + 0.5)` of a user value (UB outside int range) in
  `com_let.c` (an index expression), `options.c` (`set numdgt`/`rawfileprec`/
  `measureprec`), and `com_measure2.c` (`meas ... rise/fall/cross`);
- `cx_mtimeavg`, whose averaging window walks the scale data for `j < length - 1`, so a
  vector longer than its plot scale (`mtimeavg(unitvec(200))`) read past the scale.

Fix: a clamping helper per file before each cast, and the same length-vs-scale guard
`cx_integ`/`cx_deriv` got in Enhancement-278. In-range values are unchanged.

## Verify

```
python3 verify_castguard.py
```

Seven checks: `set numdgt=1e30`, `set rawfileprec=1e30`, `set numdgt=-1e30`,
`meas ... rise=1e308`, `mtimeavg(unitvec(200))` are clean; valid `set numdgt=6` and
`mtimeavg(vx)` still work.
