# Enhancement-278 — ngspice: transform functions guard a length/scale mismatch

Continuing the expression-layer fuzz, `integ`, `deriv`, and `ifft` were found to
overrun the heap when handed a vector whose length differs from its plot scale —
`cmath4.c:500` on `integ(unitvec(200))`, `cmath4.c:1065` on `ifft(vector(5))`,
`cmath4.c:407` on `deriv(unitvec(200))`.

## The bug

`cx_integ`, `cx_deriv`, and `cx_ifft` index both the data (by `length`) and its plot
scale. A **synthetic** vector — `vector(n)`, `unitvec(n)`, an expression result —
carries the current plot's scale, whose length need not equal `n`:

- **data longer than the scale** (`integ`/`deriv` of `unitvec(200)` on a 66-point
  plot): the fit/accumulate loops read `pl_scale->v_realdata[i]` for `i < length`,
  past the end of the scale;
- **data much shorter than the scale** (`ifft(vector(5))` on a 66-point plot): the
  Green's inverse-FFT sizes its `datax` buffer from `N = pow2(length)` but the output
  loop writes `tpts` (= scale length) points from `datax[2*i]`, so `N < tpts` overran
  `datax`.

Only `cx_fft` had been guarded (Enhancement-225); the siblings had not.

## Fix

`src/maths/cmaths/cmath4.c`:

- **`cx_integ` / `cx_deriv`** reject a data vector **longer** than its scale (the
  direction that reads the scale out of bounds) with a clean error. A *shorter* data
  vector — as produced by `fft` (frequency-domain), where a group-delay `deriv(vp(3))`
  is legitimate — stays valid.
- **`cx_ifft`** grows its transform size `N` (and `M`) to cover the output length
  `tpts` before allocating `datax`, so a much-shorter input no longer overruns it.
  This is a no-op for a well-formed transform, where `pow2(length) >= tpts` already —
  the `fft` → `ifft` round-trip is unchanged.

## Verification

`examples/scaleguard_examples/verify_scaleguard.py` (5 checks): `integ(unitvec(200))`,
`deriv(unitvec(200))`, and `ifft(vector(5))` each resolve cleanly (no overflow); the
`fft` → `ifft` round-trip still returns a full-length vector; and valid `integ(vx)` /
`deriv(vx)` still work. A transform stress over mixed lengths and types is clean under
ASan.

## Scope

One source file (`src/maths/cmaths/cmath4.c`). Completes for `integ`/`deriv`/`ifft`
the length/scale guarding that Enhancement-225 gave `fft`.
