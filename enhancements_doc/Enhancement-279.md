# Enhancement-279 — ngspice: the remaining unguarded `(int)` casts and scale-dependent transform

A systematic audit — grep for every `(int) floor/fabs(...)` of a runtime double, plus
every cmaths routine taking a `struct plot *` and whether it guards its length against
the scale — found the tail of two classes already fixed elsewhere, at sites the fuzzer
had not reached.

## The bug

**Unguarded `(int) floor(x + 0.5)` of a user-supplied double** (undefined behaviour
outside `int` range, the Enhancement-273/-274/-276 class):

- `src/frontend/com_let.c` — an index expression in an indexed `let`;
- `src/frontend/options.c` — `set numdgt` / `rawfileprec` / `measureprec`
  (`set numdgt=1e30` tripped UBSan);
- `src/frontend/com_measure2.c` — `meas … rise/fall/cross=<n>`.

**An unguarded scale-dependent transform** (the Enhancement-278 class): `cx_mtimeavg`
walks the scale data `dsc[j]` for `j < length - 1`, so a vector longer than its plot
scale — `mtimeavg(unitvec(200))` on a shorter plot — read past the scale
(AddressSanitizer heap-buffer-overflow).

## Fix

- A small clamping helper per file (`let_idx_int`, `opt_int`, `meas_int`) converts the
  value to `int` only after clamping to `int` range (mapping `NaN` to 0), so an
  out-of-range option or count saturates instead of invoking UB. Values already in
  range are unchanged.
- `cx_mtimeavg` gets the same length-vs-scale guard `cx_integ` / `cx_deriv` received in
  Enhancement-278: an input longer than its scale is rejected with a clean error.

## Verification

`examples/castguard_examples/verify_castguard.py` (7 checks): `set numdgt=1e30`,
`set rawfileprec=1e30`, `set numdgt=-1e30`, `meas … rise=1e308`, and
`mtimeavg(unitvec(200))` are all clean where they previously tripped UBSan/ASan; and a
valid `set numdgt=6` and `mtimeavg(vx)` still work.

## Scope

Four source files, guard-only changes. No valid option, measurement, index, or
transform result changes.
