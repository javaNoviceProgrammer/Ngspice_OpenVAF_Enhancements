# ifftreal_examples — Enhancement-275

`cx_ifft` (`src/maths/cmaths/cmath4.c`) always cast its input to `ngcomplex_t *`. For a
real input vector (`double[length]`, length*8 bytes), reading `length` complex elements
(length*16 bytes) ran 2x past the buffer -- an AddressSanitizer heap-buffer-overflow
READ. `cx_fft` (Enhancement-225) already distinguishes real and complex input; ifft did
not.

Fix: for a real input, build a complex array (imag = 0), use it, and free it; a length
>= 2 guard rejects a degenerate input. Valid complex ifft is unchanged.

## Verify

```
python3 verify_ifftreal.py
```

Three checks: `ifft(vx)` on a real vector runs clean; the fft->ifft round-trip keeps
the length; complex `ifft` still works.
