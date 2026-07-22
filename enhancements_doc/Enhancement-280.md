# Enhancement-280 — ngspice: an out-of-range `let v[i] = x` wrote past the end of the vector

While hardening the index cast (Enhancement-279) the clamp exposed a far more serious
defect underneath: an out-of-range **single** index in an indexed `let` assignment was
never bounds-checked at all.

## The bug

`get_index_values` (`src/frontend/com_let.c`) parses either one index (`v[i]`) or a
range (`v[lo:hi]`). It validates `low > high` and `high >= n_elem_this_dim` — but
those checks lived **inside the range branch only**. The single-index path set
`high = low` and returned completely unchecked, so

```spice
let vx[100] = 1        # on a 66-element vector
```

walked straight into the byte-offset arithmetic and performed a
**heap-buffer-overflow WRITE** (AddressSanitizer: `WRITE of size 8`). That is memory
corruption from an ordinary typo — no exotic input required. A very large index also
overflowed the `index * n_byte_elem` product in `int`. The range form `vx[0:999]` was
correctly rejected all along.

## Fix

`src/frontend/com_let.c`: move both checks out of the range branch so they validate a
**single index too**. An out-of-range assignment now reports
`index/high range (N) exceeds the maximum value (M)` and changes nothing.

Reads are unaffected — `op_ind` clamps an out-of-range read index with a warning
(Enhancement-274) — and every valid assignment, including the last element and the
range form, behaves exactly as before.

## Verification

`examples/letidxoob_examples/verify_letidxoob.py` (6 checks): `let w[10] = 99` on a
10-element vector, `let w[999] = 99`, and `let w[1e308] = 99` are each rejected cleanly
where the first two previously corrupted the heap; the last valid index
(`let w[9] = 42`) and a mid-vector assignment still assign; and the range form is still
rejected.

## Scope

One source file (`src/frontend/com_let.c`), moving two existing checks so they cover
both index forms.
