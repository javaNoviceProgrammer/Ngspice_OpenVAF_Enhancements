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

## The demos

**(A) `pyplotcontour_demo.cir` — an analytic surface.** A grid built in
`.control` with a **known** surface so the contour can be checked, not just
rendered:

- `z = x² + y²` over `x, y ∈ [-2, 2]` → concentric circular contours (a
  paraboloid: `z = 0` at the centre, `z = 8` at the corners).

**(B) `bridge_dc_demo.cir` — a real nested `.dc` sweep.** The everyday use: a
diode-OR bridge whose output `V(c)` follows whichever of its two inputs is
higher. A nested `.dc` sweeps both inputs; since `v1` drives node `a` and `v2`
drives node `b`, `V(a)`/`V(b)` are the two swept values at every point, so
`pyplot -contour v(c) v(a) v(b)` maps the output over the `(V(a), V(b))` plane —
a max-like corner surface rising toward the top and right edges. This shows the
feature on genuine simulation output (not just `.control` math), with the
`turbo` colormap and labelled contour lines.

## What is verified

`verify_pyplotcontour.py` (19 checks, both solvers) runs **both** decks and
parses the generated `.data`/`.py` and PNGs.

For (A) the analytic surface:
1. the `-contour` path is taken (`tricontourf`, not `plot`/`hist`; a colorbar
   labelled `z`; axes labelled `x`/`y`);
2. the data table has **three** columns `(x, y, z)`, all `N` rows;
3. the column mapping is correct — `z` reconstructs `x² + y²` from the `.data`;
4. the sweep is genuinely 2-D — `x` and `y` each span a real range, and `z` runs
   from ~0 at the grid centre to ~8 at a corner;
5. a valid, non-trivial PNG is rendered.

For (B) the real nested `.dc`:
1. the `-contour` path is taken with the requested knobs (`tricontourf`,
   `cmap=turbo`, overlaid lines; colorbar `v(c)`, axes `v(a)`/`v(b)`);
2. the nested `.dc` produced the flattened 51×51 = 2601-row, 3-column grid;
3. the axes are the two real swept sources (`V(a)`, `V(b)` each span `[-1, 1]`);
4. the output is the diode-OR surface — ~0 when both inputs are low, rising when
   **either** input is high, maximal at the both-high corner (confirms the
   columns map correctly onto a genuine circuit result);
5. a valid PNG is rendered.

## Run

```sh
python3 verify_pyplotcontour.py
```
