# pyplotcontour_examples — Enhancement-218: `pyplot -contour`

`pyplot -contour <z> <x> <y>` renders a 2-D **contour map** of a quantity `z`
over the `(x, y)` plane — the natural view of a 2-D parameter sweep:

```
pyplot -contour i(vd) vgs vds          # a device current over a (Vgs, Vds) grid
pyplot -contour gain rval cval         # a gain surface over an (R, C) grid
pyplot mymap -contour p x y            # named output (mymap.py/.data/.png)
```

The three arguments are the **height/colour** (`z`) and the two **axes** (`x`,
`y`), each a flattened, equal-length sweep vector. matplotlib triangulates the
`(x, y)` points (`tricontourf`), so **gridded or scattered** sweep data plots
with no grid-dimension metadata needed. Where do `x`, `y`, `z` come from? Any
2-D sweep that leaves three equal-length vectors — a nested `.dc`, the `sweep`
command family ([E-146](../../enhancements_doc/Enhancement-146.md),
[E-190](../../enhancements_doc/Enhancement-190.md)), a `.step` grid, or vectors
you build in `.control`.

It reuses the entire `pyplot` pipeline
([E-94](../../enhancements_doc/Enhancement-94.md) onward) — the matplotlib back
end, `set pyplot_terminal=png|svg|pdf` for a headless render, styles, figure
size, backend. Three contour-specific knobs are added:

- `set pyplot_contour_levels=<N>` — number of contour levels (default: let
  matplotlib choose);
- `set pyplot_contour_lines` — overlay labelled black contour lines on the
  filled map;
- `set pyplot_contour_cmap=<name>` — the colormap (default `viridis`).

## The demo

`pyplotcontour_demo.cir` builds a grid with a **known analytic surface** so the
contour can be checked, not just rendered:

- `z = x² + y²` over `x, y ∈ [-2, 2]` → concentric circular contours (a
  paraboloid: `z = 0` at the centre, `z = 8` at the corners).

## What is verified

`verify_pyplotcontour.py` (9 checks, both solvers) parses the generated
`.data`/`.py` and the PNG:
1. the `-contour` path is taken (`tricontourf`, not `plot`/`hist`; a colorbar
   labelled `z`; axes labelled `x`/`y`);
2. the data table has **three** columns `(x, y, z)`, all `N` rows;
3. the column mapping is correct — `z` reconstructs `x² + y²` from the `.data`;
4. the sweep is genuinely 2-D — `x` and `y` each span a real range, and `z` runs
   from ~0 at the grid centre to ~8 at a corner;
5. a valid, non-trivial PNG is rendered.

## Run

```sh
python3 verify_pyplotcontour.py
```
