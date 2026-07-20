# Degenerate / undersized table hardening (Enhancement-247)

Two out-of-bounds bugs in the XSPICE **`table2d`** and **`table3d`** code models,
found by fuzzing table dimensions and confirmed with AddressSanitizer /
UndefinedBehaviorSanitizer.

Both models read a lookup table from a file: line 1 is the x-axis point count
(`ix`), line 2 the y count (`iy`) [line 3 the z count (`iz`) for 3-D], then the
axis values and the data grid. The loader never validated those counts, so a
small table broke two ways:

**1. Out-of-range ramp (OOB read).** For an input beyond the table edge the model
ramps the derivative to zero using `xcol[1] - xcol[0]` (low side) or
`xcol[ix-1] - xcol[ix-2]` (high side). A single-point axis (`ix==1`) has no
`xcol[1]` / `xcol[-1]`:

```
ERROR: AddressSanitizer: heap-buffer-overflow ... READ of size 8
    #0 ... in cm_table2D cfunc.c:298
```

**2. ENO interpolation (OOB/UB).** The Madagascar ENO interpolation of order `p`
reads a stencil that needs `2*(p-1)` points per axis. The `order` parameter
**defaults to 3**, which needs ≥ 4 points per axis — but the loader only clamped
it *up* to a minimum of 2, never *down* to what the table supports. So the
default order on any table with a `< 4`-point axis (a 3×3 table, or a 3-D table
with a 2-plane `z` axis like the shipped `test-3d-1.table`) ran off the stencil:

```
UndefinedBehaviorSanitizer: undefined-behavior mada/eno2.c:131
UndefinedBehaviorSanitizer: undefined-behavior mada/eno3.c:148
```

**Fix.** Right after the existing `order >= 2` floor, reject any axis with `< 2`
points (a 1-point axis can be neither ramped nor interpolated) and clamp the
interpolation order down to `mindim/2 + 1` (the inverse of the `2*(p-1)`
stencil requirement). A small table then interpolates at a reduced but **valid**
order instead of reading out of bounds. Tables large enough for the requested
order are byte-identical — every shipped example has `mindim/2 + 1 >= order`.

`verify_tablefix.py` (6 checks, both solvers): a valid 8×8 order-3 `table2d`
interpolates exactly (`out = x + 10y` at `(2.5, 3.0)` → `32.5`); a single-x-point
table and a degenerate 3-D table (`iz=1`) are rejected with a clean error and no
crash; and small 3×3 / 3×3×3 order-3 tables now run (order clamped) without
crashing.

```
python3 verify_tablefix.py
```

The code models load from the prebuilt bundle via `SPICE_LIB_DIR` (pointed at
`bin/<os>/<arch>/` by `_setup`); the test self-skips if that bundle is absent.

## Scope

XSPICE code models only (`xspice/icm/table/table2D`, `.../table3D`). No change to
the ngspice binary, the solver, or any analysis; tables large enough for the
requested interpolation order are unaffected.
