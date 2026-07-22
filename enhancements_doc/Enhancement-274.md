# Enhancement-274 — ngspice: an out-of-range vector index no longer invokes UB

A fuzz of the expression layer (an extension of the Enhancement-270…-273 campaign)
flagged `src/frontend/evaluate.c:779` on `v(a)[1e308]`.

## The bug

`op_ind` (vector indexing, `v[expr]`) rounds the index with
`(int) floor(value + 0.5)`. Casting a `double` that is non-finite or outside `int`
range to `int` is undefined behaviour, so `v(a)[1e308]` (or an `inf`/`NaN` index)
tripped UBSan. The code *already* clamps the resulting index to `[0, majsize-1]`
with a warning — the only defect was the cast itself, which runs before that clamp.

## Fix

`src/frontend/evaluate.c`: a helper `idx_floor()` clamps the value to `int` range
(and maps `NaN` to 0) before the cast, so the existing `[0, majsize-1]` clamp then
handles it. `v(a)[1e308]` now resolves to the last element (with the pre-existing
"upper limit" warning) exactly as a large in-range index already did — no UB.

Applied to all three index casts (the real index, and the real/imag parts of a
complex `[lo,hi]` range index).

## Verification

`examples/idxcast_examples/verify_idxcast.py` (5 checks): `vx[1e308]`, `vx[1e30]`,
and a `NaN` index each resolve cleanly (no UB, no crash) where they tripped UBSan;
and a valid `vx[0]` and range `vx[0:2]` still return the right elements.

## Scope

One source file (`src/frontend/evaluate.c`). No change to any valid index.
