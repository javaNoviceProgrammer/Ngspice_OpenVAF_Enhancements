# Enhancement-22 — natural cubic-spline `$table_model` (version11)

This document describes the source-code change made to **OpenVAF-r** in the
`version11/` directory to add **natural cubic-spline** interpolation to
`$table_model`, extending the piecewise-**linear** interpolation of
Enhancement-16 (1-D) and the **multilinear** interpolation of Enhancement-17
(2-D/3-D). A cubic spline is **C¹** — its derivative is continuous — so a
table-based compact model's `gm`/`gds` are smooth, unlike the staircase
derivative produced by linear interpolation.

## Selecting cubic interpolation

The interpolation degree is chosen entirely by the `$table_model` **control
string** — no new builtin signature and no OSDI/ngspice change. A `3` anywhere in
the control string selects natural cubic spline; otherwise interpolation stays
multilinear. Extrapolation is unchanged (`L` = linear, else clamp). Following
Enhancement-16/17's simplification, a control code applies to all axes (per-axis
degree is future work). So this is a **`hir_lower`-only** change (`expr.rs`).

## How it lowers to differentiable MIR

The key observation is that a natural cubic spline's per-point second derivatives
(the "moments" `M`) solve a tridiagonal system that is **linear in the grid values
`y` and depends only on the grid**:

```
M = L · y      with L (n×n) fixed by the grid alone (natural BC: M[0]=M[n-1]=0)
```

`natural_cubic_spline_moment_matrix(grid)` precomputes `L` at compile time
(building the interior tridiagonal system and inverting it with a small dense
Gauss–Jordan). At lowering time each moment `M[i] = Σ_j L[i][j]·vals[j]` is then
just a **constant-weighted sum of the (possibly runtime) grid values** — no
runtime linear solve. The per-interval cubic

```
S(x) = M[i]·a³/(6h) + M[i+1]·b³/(6h) + (v[i]/h − M[i]·h/6)·a + (v[i+1]/h − M[i+1]·h/6)·b
       with a = x[i+1]−x, b = x−x[i], h = x[i+1]−x[i]
```

is emitted as ordinary MIR and selected per interval with the same `x ≥ grid[i]`
select chain the linear kernel uses, so `mir_autodiff` supplies the exact,
**continuous** Jacobian for free. Extrapolation mirrors the linear kernel: clamp
to the endpoint value, or (with `L`) continue the spline's end tangent (also a
constant-weighted combination of the values).

For N-D, the existing recursive-1-D scheme (`interp_nd`) is reused with the cubic
kernel at each level; because a natural spline interpolates exactly at nodes,
recursive-1-D natural spline equals the exact **tensor-product** natural spline.

### Functions (`hir_lower/src/expr.rs`)

- `natural_cubic_spline_moment_matrix(grid) -> Vec<Vec<f64>>` — compile-time `L`.
- `weighted_sum(w, vals)` — `Σ wⱼ·valsⱼ` in MIR (constant weights, runtime values).
- `interp_1d_spline(x, grid, vals, linear_extrap)` — the cubic kernel (falls back
  to `interp_1d_values` for fewer than 3 points).
- `interp_nd` gains a `cubic` flag dispatching to the spline or linear kernel;
  `lower_table_model` derives `cubic` from the control string (`'3'`).

## Verification

`examples/cubic_table_examples/verify_cubic_table.py` (`ALL PASS`), each check contrasting
cubic with linear on the same data:

- **accuracy** — cubic tracks `sin(V)` ~46× better than linear at off-grid points;
- **smoothness** — across a grid node the cubic `gm` matches `|cos(V)|` on both
  sides (continuous), while the linear `gm` jumps ~10× more — the defining benefit
  of splines, and a direct test that the autodiff Jacobian through the cubic MIR is
  continuous;
- **exactness** — a natural cubic spline reproduces straight-line data exactly
  (all moments zero);
- **N-D** — 2-D tensor-product cubic reproduces `sin(x)·cos(y)` accurately.

The existing linear `table_model_examples`/`mdtable_examples` still pass unchanged
(the linear path is untouched), and every other example folder still passes.

## Known limitations

- Natural boundary conditions only (zero end curvature); other end conditions
  (clamped, not-a-knot) are future work.
- A control code applies cubic to all axes; per-axis interpolation degree is
  future work.
- The moment matrix is dense (`O(n²)` weighted-sum terms per moment); fine for the
  modest grids typical of compact-model tables, heavier for very large grids.
