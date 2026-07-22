# idxcast_examples — Enhancement-274

Vector indexing (`v[expr]`) in `op_ind` (`src/frontend/evaluate.c`) rounded the index
with `(int) floor(value + 0.5)`. Casting a `double` outside int range to `int` is
undefined behaviour, so `v(a)[1e308]` (or an inf/NaN index) tripped UBSan. The code
already clamps the resulting index to `[0, majsize-1]`; only the cast was unsafe.

Fix: an `idx_floor()` helper clamps the value to int range (NaN -> 0) before the cast.
`v(a)[1e308]` now resolves to the last element (with the pre-existing warning); valid
indices are unchanged.

## Verify

```
python3 verify_idxcast.py
```

Five checks: `vx[1e308]`, `vx[1e30]`, and a NaN index each resolve cleanly; valid
`vx[0]` and range `vx[0:2]` still return the right elements.
