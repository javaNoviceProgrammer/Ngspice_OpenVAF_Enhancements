# Enhancement-285 — ngspice: output paths indexed one vector by another's length

The extreme-data output fuzz's remaining findings all turned out to be one class, in
four places: a vector's **own length** need not equal its plot **scale's** length, and
a **complex** vector's `v_realdata` is `NULL`. The output paths assumed otherwise.

## The bug

Any synthetic vector carries the current plot's scale, so `let y = vector(8)` on a
66-point transient plot has 8 points and a 66-point scale. And a complex vector holds
its data in `v_compdata` — the dvec union leaves `v_realdata` **NULL**.

- **`plotit.c`** — the transient resampling passed `v->v_realdata` together with
  `v->v_scale->v_length` to `ft_interpolate()`, which indexes the *data* by that
  length: reading ~58 elements past a shorter vector. For a **complex** vector it
  passed `NULL` outright — a **hard SEGV** on the shipped build
  (`asciiplot sqrt(-1*vector(10))` returned `rc = 139`).
- **`agraf.c`** — the bracketing indices `lower`/`upper` are computed against the X
  scale and bounded by `xscale->v_length`, but they were then used to index each
  plotted **vector**.
- **`gnuplot.c`** (`wrdata`) — the "no more data" guard tested only
  `i >= scale->v_length`, while the branch it protects indexes `v->v_realdata[i]`.
- **`com_measure2.c`** — the plain tran/dc branch read `d->v_realdata[i]` and
  `dScale->v_realdata[i]` with no NULL check, though the `ac`/`sp` branches beside it
  already had one. Measuring a complex vector dereferenced NULL. (Present twice, in
  `measure_at()` and `measure_deriv_at()`.)

## Fix

Each index is clamped to the vector it actually addresses:

- `plotit.c` — pass the length the data and scale *share*, and skip the transient
  resampling entirely when any vector is not real (`all_vecs_real()`), since that
  block replaces the shared scale and must convert all vectors or none. Complex
  vectors continue to plot through the normal path.
- `agraf.c` — clamp `lower`/`upper` into `[0, v->v_length - 1]` per vector.
- `gnuplot.c` — the guard now also requires `i < v->v_length`.
- `com_measure2.c` — take the real part when `v_realdata` is NULL, exactly as the
  `ac`/`sp` branches do.

## Verification

`examples/veclenmix_examples/verify_veclenmix.py` (7 checks): a vector shorter than
its scale, a vector longer than its scale, a complex vector (previously `rc = 139`),
`wrdata` of a short vector, and a measure over a complex vector are all clean and
still render/measure; an ordinary `asciiplot v(b)` and `meas tran … max v(b)` are
unaffected. Ordinary plot output and `wrdata` output were diffed against the pre-fix
binary and are **byte-identical**. All eight decks from the output fuzz are clean.

## Scope

Four source files, guard/clamp only. No change to any ordinary plot, write or measure.
