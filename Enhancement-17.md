# Enhancement-17 — multi-dimensional `$table_model` (version11)

This document describes the source-code changes made to **OpenVAF-r** in the
`version11/` directory to generalise the 1-D `$table_model` of Enhancement-16 to
**multiple dimensions** (2-D and 3-D): `$table_model(x1, x2[, x3], "grid_file"
[, "control"])` interpolates a value from an N-dimensional tabulated grid.

Like the 1-D case, the interpolation must be **differentiable** (it is used in the
main device equations, so every partial derivative becomes a Jacobian entry). It
is verified end-to-end through ngspice — see `mdtable_examples/`.

All work is in `version11/`; verification uses `version11/ngspice-46`'s own
binary and `version11/OpenVAF-master`'s own `openvaf-r`. **No OSDI ABI change and
no ngspice change were needed.**

## Design: N-D multilinear = recursive 1-D interpolation

Multilinear interpolation is separable, so an N-D interpolation is built from 1-D
interpolations recursively: **peel the outermost axis**, interpolate each of its
grid slices over the remaining `N-1` axes (yielding one runtime value per
outer-axis grid line), then interpolate those values along the outer axis. The
base case (one axis left) is an ordinary 1-D interpolation of the tensor's
constant values. Because each step is the same differentiable piecewise-linear
1-D kernel, the whole thing is differentiable in every coordinate — `mir_autodiff`
supplies all N partial derivatives (e.g. a table-based MOSFET's `gm` and `gds`)
for free, with no special support.

The shared 1-D kernel, `interp_1d_values`, was generalised from Enhancement-16's
1-D lowering to interpolate a list of **runtime `Value`s** (the sub-results of the
recursion) rather than only compile-time constants, using an `fdiv` for the
segment slope so the pure-1-D path stays bit-identical to Enhancement-16.

## 1. Signatures

`hir_ty/builtin.rs` adds four file-based variants to the `TABLE_MODEL` group
(alongside the existing 1-D ones): `TABLE_MODEL_2D_FILE`, `..._2D_FILE_CTRL`,
`TABLE_MODEL_3D_FILE`, `..._3D_FILE_CTRL` — one `Val(Real)` coordinate per
dimension, a `Literal(String)` grid-file name, and an optional control string. The
fixed-signature type checker resolves the right variant by argument count and
types (a 2-D call `(Real, Real, String)` vs a 1-D file+control `(Real, String,
String)` differ in the second argument).

## 2. Grid data file

Multi-dimensional data is a **self-describing grid file** (`read_table_grid_nd`
over `read_table_tokens`): whitespace-separated tokens — `ndim`, then `ndim` axis
sizes, then each axis's ascending coordinates, then `prod(sizes)` values in
row-major order (outermost axis slowest) — with blank/`#`/`//`/`*` lines ignored.
1-D still accepts an inline `'{x0,y0,...}` array or a two-column data file.

## 3. Lowering (`lower_table_model`, `interp_nd`, `interp_1d_values`)

`lower_table_model` maps the resolved signature to `(ndim, is_file, has_ctrl)`,
reads the grid into per-axis coordinate vectors and a row-major value tensor,
lowers each coordinate expression, and calls `interp_nd`. `interp_nd` performs the
recursive peel-and-blend described above; `interp_1d_values` is the differentiable
piecewise-linear select chain (segment `i` active once `x >= grid[i]`; constant or
linear extrapolation outside). Everything lowers to ordinary MIR
(`fsub`/`fdiv`/`fmul`/`fadd` + `make_select`), so it is differentiable and works
identically in DC, AC and transient.

## Verification

- `mdtable_examples/verify_mdtable.py` — a table-based MOSFET `I(Vgs, Vds)`:
  - **DC** — the drain current over a `(Vgs, Vds)` scan matches a reference
    bilinear interpolation of the same grid to machine precision (~1e-19 A);
  - **AC** — both partial derivatives, `gm = dId/dVgs` and `gds = dId/dVds`, match
    the bilinear surface gradient (~1e-16 S), i.e. the 2-D Jacobian is exact.
- Ad-hoc checks confirm **bilinear** reproduces `x·y` and **trilinear** reproduces
  `x·y·z` exactly (multilinear functions), with both/all partial derivatives
  correct.
- The 1-D `table_model_examples` (Enhancement-16) still passes unchanged
  (DC/AC/transient), confirming the shared-kernel refactor did not regress 1-D.
- The `hir_def`/`hir_ty`/`hir`/`hir_lower` unit-test suites pass with no
  regressions; the pre-existing stale `sim_back` snapshot failures are unchanged
  and unrelated.

## Known limitations / future work

- Dimensionality is **1-D, 2-D, 3-D** (the practical range for compact-model
  tables). A truly variadic (arbitrary-N) form would need a special-cased builtin
  rather than fixed per-dimension signatures; the `interp_nd` lowering is already
  general in N.
- Interpolation is **multilinear** (degree 1). Higher-degree (spline) interpolation
  remains future work.
- Multi-dimensional data must come from a grid **file** (an inline array is 1-D
  only); axis coordinates must be ascending.
