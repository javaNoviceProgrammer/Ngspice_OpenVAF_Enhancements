# scaleguard_examples — Enhancement-278

`cx_integ`, `cx_deriv`, and `cx_ifft` (`src/maths/cmaths/cmath4.c`) index both the data
(by `length`) and its plot scale. A synthetic vector whose length differs from the
current plot's scale overran the heap:

- data LONGER than the scale (`integ(unitvec(200))` / `deriv(unitvec(200))`) read the
  scale out of bounds;
- data much SHORTER than the scale (`ifft(vector(5))`) overran the Green's inverse-FFT
  `datax` buffer (sized from the input length, but the output loop writes scale-length
  points).

Only `cx_fft` had been guarded (Enhancement-225).

Fix: integ/deriv reject a data vector longer than its scale (a shorter one, as from
fft, stays valid); ifft grows its transform size N to cover the output length before
allocating. The fft->ifft round-trip and valid integ/deriv are unchanged.

## Verify

```
python3 verify_scaleguard.py
```

Five checks: `integ(unitvec(200))`, `deriv(unitvec(200))`, `ifft(vector(5))` resolve
cleanly; the fft->ifft round-trip still returns a full-length vector; valid
`integ(vx)`/`deriv(vx)` still work.
