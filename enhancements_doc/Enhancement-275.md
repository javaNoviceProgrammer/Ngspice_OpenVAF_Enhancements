# Enhancement-275 — ngspice: `ifft()` on a real vector no longer reads past its buffer

The expression-layer fuzz flagged `src/maths/cmaths/cmath4.c:1019` on `ifft(vx)`
where `vx` is a real vector.

## The bug

`cx_ifft` unconditionally reinterpreted its input as complex:

```c
ngcomplex_t *indata = (ngcomplex_t *) data;
```

For a `VF_REAL` input, `data` is a plain `double[length]` (length × 8 bytes), so
reading `indata[i]` for `i < length` walks `length` **complex** elements
(length × 16 bytes) — twice past the buffer. AddressSanitizer reported a
`heap-buffer-overflow READ` (the input was a 528-byte / 33-element region read as
66 complex elements). `cx_fft` (Enhancement-225) already distinguishes real and
complex input; `cx_ifft` did not.

## Fix

`src/maths/cmaths/cmath4.c`: for a `VF_REAL` input, build a proper complex array
(imaginary part 0) sized `length`, use it, and free it before returning; a
`VF_COMPLEX` input still points straight at `data`. A `length >= 2` guard (matching
`cx_fft`) rejects a degenerate input up front.

## Verification

`examples/ifftreal_examples/verify_ifftreal.py` (3 checks): `ifft(vx)` on a real
vector runs with no overflow where it previously read out of bounds; the
`fft` → `ifft` round-trip returns a vector of the same length; and `ifft` of a
genuinely complex vector still works.

## Scope

One source file (`src/maths/cmaths/cmath4.c`). No change to a valid complex `ifft`.
