# Enhancement-209 — `hb` publishes its spectrum as nutmeg vectors

The [`hb`](Enhancement-134.md) harmonic-balance command used to **only print** a
spectrum table — the converged Fourier coefficients were freed as soon as the table
was written, so there was no way to `plot`, `print`, or `wrdata` the result without
scraping stdout. (The `amp2n2222` HB reproduction study had to parse that table in
Python for every figure.) `hb` now **publishes its spectrum as ngspice vectors**, so
the result is directly accessible like any AC/tran result.

## What it does

After a converged `hb <f0> <K>`, a fresh **`hb` plot** is created and left current,
containing:

- **`hbfrequency`** — a real scale vector: `0, f0, 2·f0, …, K·f0` (K+1 points);
- one **complex vector per node** (named by the node, e.g. `out`, `vcc`,
  `q1#branch`), carrying the **single-sided amplitude** at each harmonic — so
  `mag(out)` and `vp(out)` reproduce the `|V|` and phase columns of the printed
  table exactly.

```
hb 100meg 8
plot mag(out)                 * the output spectrum
print vdb(out)                * in dB
wrdata spec.dat mag(out) vp(out)
```

All the usual accessors work (`v(out)`, `vm(out)`, `vdb(out)`, `vp(out)`,
`mag(out)`, `real(out)`, …), because the vectors are ordinary complex nutmeg
vectors on a frequency scale. The printed table is **kept** (backward compatible),
and the `.hb` dot-card publishes the same vectors.

## Implementation

`HBanalyze()` (`spicelib/analysis/dcpss.c`) already computed the two-sided Fourier
solution `Vr/Vi` and then freed it. It gains an optional out-parameter
`struct hbspectrum *out` (declared in `cktdefs.h`): on convergence it hands the
`Vr/Vi` arrays (and `N`, `K`, `f0`) to the caller instead of freeing them.

The frontend command `com_hb()` (`frontend/com_hb.c`) receives that struct and, in
a new `hb_publish()`, builds the plot with the frontend vector API
(`plot_alloc`/`plot_new`/`plot_setcur`, `dvec_alloc`/`vec_new`) — the same idiom the
`stb` and `eye` commands use. Node names come from `CKTnames`; a name containing
`#branch` is typed `SV_CURRENT`, otherwise `SV_VOLTAGE`. The single-sided scaling
(`×2` for `k>0`, `×1` for DC) matches the table. The command then frees the
transferred arrays.

The vectors are published from the **frontend** (not from the analysis layer) so no
analysis `JOB` is required — a bare `hb` in a `.control` block, which may leave
`CKTcurJob` unset, publishes cleanly.

## Verification

[`examples/hb_examples/verify_hb.py`](../examples/hb_examples/verify_hb.py) gains a
check (9 total): after `hb 100meg 5` on a diode rectifier, the published
`hbfrequency` + node vectors exist, and `print mag(n)` equals the printed table's
`|V|` column bit-for-bit across all six harmonics. The existing table-based checks
(and the `.hb` dot-card parity) are unchanged.

## Scope

ngspice-only, purely additive. The numerical HB core is untouched — this only
exposes the already-computed spectrum as vectors. `qpss`/`hb`-family analyses that
print their own tables (two-tone `qpss`, `pac`, …) are unaffected.
