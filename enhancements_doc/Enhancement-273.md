# Enhancement-273 — ngspice: cmaths integer operators guard their `(int)` casts

A continued ASan/UBSan fuzz of the expression layer (the same campaign as
Enhancement-270…-272) flagged `../../../../src/maths/cmaths/cmath2.c:765` on the
input `1e30 % 5`. It is one of a small cluster of the same defect: an expression
routine converts a `double` operand to `int` with a plain cast.

## The bug

Casting a `double` that is non-finite or outside `int` range to `int` is undefined
behaviour. Two reachable paths in `cmath2.c`:

- **`cx_mod` (the `%` operator)** computed `(int) floor(fabs(op))` for each operand.
  `1e30 % 5` is UB (UBSan flagged it) and, on the *shipped* build, returned a garbage
  value (`2`) rather than an error — a silently wrong result.
- **`cx_vector` / `cx_cvector` / `cx_unitvec`** set the result length with
  `(int) fabs(arg)`. `vector(1e30)` / `unitvec(1e30)` produced a saturated
  (`INT_MAX`-ish) length, and the routine then allocated and filled it — a
  multi-gigabyte allocation (macOS over-commit lets the `calloc` succeed) followed
  by a billion-iteration fill loop, i.e. an apparent **hang** on the shipped build
  (`rc = 142` under a watchdog), not merely a sanitizer report.

## Fix

`src/maths/cmaths/cmath2.c` — range-check before every `(int)` cast:

- `cx_mod` floors each operand into a `double`, then `rcheck`s it lies in
  `[0 or 1, INT_MAX]` before casting; a non-finite or too-large operand takes the
  existing `"argument out of range for mod"` error path (`rcheck` → `EXITPOINT`,
  returns `NULL`).
- A shared helper `cx_veclen()` validates the length argument for the three vector
  builders (`fabs`/`cmag` are `≥ 0`, so one `≤ INT_MAX` check also rejects `NaN`/
  `inf`); an out-of-range length prints `"vector length ... is out of range"` and
  returns `NULL`, which `apply_func` already handles.

Valid expressions are unchanged: `17 % 5 == 2`, `vector(4) == [0,1,2,3]`,
`unitvec(3) == [1,1,1]`, and any length within `int` range behaves exactly as
before.

## Verification

`examples/mathcast_examples/verify_mathcast.py` (5 checks): `1e30 % 5`,
`vector(1e30)`, and `unitvec(1e30)` each error cleanly and quickly (no UB, no hang,
no garbage) where they previously tripped UBSan / returned garbage / hung; and valid
`17 % 5`, `vector(4)` still evaluate correctly. Full dual-solver example regression
passes.

## Scope

One source file (`src/maths/cmaths/cmath2.c`). No change to any valid expression.
