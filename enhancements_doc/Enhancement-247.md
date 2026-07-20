# Enhancement-247 — degenerate / undersized table hardening (`table2d`, `table3d`)

Two out-of-bounds bugs in the XSPICE `table2d` and `table3d` code models, found
by fuzzing table dimensions and confirmed with AddressSanitizer /
UndefinedBehaviorSanitizer. Third area of the XSPICE code-model deep dive (after
E-240 `s_xfer` and E-246 `pwl`/`pwlts`).

## The bugs

Both models read a lookup table from a data file whose first lines are the axis
point counts: line 1 = `ix` (x points), line 2 = `iy` (y points), and for the 3-D
model line 3 = `iz` (z points), followed by the axis values and the data grid.
The loader (`init_local_data`) accepted whatever counts the file declared without
a sanity check, so a small table broke in two independent ways.

### 1. Out-of-range ramp — heap OOB read

For an input outside the table the model clamps to the nearest edge and ramps the
partial derivative to zero, using the spacing of the two edge points:

```c
/* low side */   xramp = 1 - ((xcol[0]-xval) / (RAMP_WIDTH*(xcol[1]-xcol[0])));
/* high side */  xramp = 1 - ((xval-xcol[ix-1]) /
                              (RAMP_WIDTH*(xcol[ix-1]-xcol[ix-2])));
```

A **single-point axis** (`ix == 1`) has only `xcol[0]`, so `xcol[1]` (low side) or
`xcol[ix-2] == xcol[-1]` (high side) is out of bounds:

```
ERROR: AddressSanitizer: heap-buffer-overflow ... READ of size 8
    #0 ... in cm_table2D cfunc.c:298
```

`table3d` has the identical ramp for all three axes.

### 2. ENO interpolation — OOB / undefined behaviour

Interpolation uses the Madagascar ENO library. An order-`p` ENO reads a stencil
that needs `2*(p-1)` points per axis (empirically: order 2 needs 2 points, order
3 needs 4, order 4 needs 6, order 5 needs 8 — `sf_eno_init` allocates
`diff[i]` with `n-i` entries and the get/apply path walks a `2*(p-1)`-wide
stencil). The `order` parameter **defaults to 3**, so a table needs ≥ 4 points on
every axis by default — but the loader only clamped `order` *up* to a minimum of
2, never *down* to what the table supports:

```c
interporder = order;
if (interporder < 2) { ...; interporder = 2; }   /* upper bound never checked */
loc->newtable = sf_eno2_init(interporder, ix, iy);
```

So the default order on any table with a `< 4`-point axis — a 3×3 table, or a 3-D
table with a 2-plane `z` axis (exactly the shipped `test-3d-1.table`, `iz=2`) —
ran off the stencil:

```
UndefinedBehaviorSanitizer: undefined-behavior mada/eno2.c:131
UndefinedBehaviorSanitizer: undefined-behavior mada/eno3.c:148
```

## The fix

Immediately after the existing `order >= 2` floor, add a dimension check and an
upper clamp (both `table2D` and `table3D`):

```c
int mindim = min(ix, iy[, iz]);
if (mindim < 2) {                    /* a 1-point axis cannot be ramped/interp'd */
    cm_message_printf("table %s: each axis needs at least 2 points ...");
    xrc = -1; goto EXITPOINT;        /* clean error instead of the ramp OOB */
}
if (interporder > mindim / 2 + 1)    /* inverse of the 2*(p-1) stencil rule */
    interporder = mindim / 2 + 1;    /* small table -> reduced but valid order */
```

A degenerate (single-point) axis is now rejected cleanly, and a small table
interpolates at the highest order its smallest axis can support instead of
reading out of bounds. Tables large enough for the requested order are
**byte-identical** — every shipped example has `mindim/2 + 1 >= order` (the
smallest shipped tables are 7×7, `mindim/2+1 = 4 >= 3`).

## Verification

`examples/tablefix_examples/verify_tablefix.py` (6 checks, both solvers): a valid
8×8 order-3 `table2d` interpolates exactly (`out = x + 10y` at `(2.5, 3.0)` →
`32.5`); a single-x-point `table2d` (`ix=1`) and a degenerate `table3d` (`iz=1`)
are rejected with a clean error and no crash; and small 3×3 / 3×3×3 order-3
tables now run (order clamped) without crashing. The out-of-bounds read and the
ENO undefined behaviour were reproduced and then shown fixed across a full
`(dimension × order)` grid under AddressSanitizer/UBSan builds of the code
models.

## Scope

XSPICE code models only (`xspice/icm/table/table2D`, `.../table3D`). Fix is in
`.cm` code models, so `table.cm` was regenerated via `cmpp` and redeployed under
`bin/*/codemodels/`; the ngspice binary itself is unchanged. No core simulator,
solver, or analysis change; tables large enough for the requested order are
unaffected. Full regression: all examples pass.
