# Enhancement-218 — `pyplot -contour` (2-D contour maps)

A 2-D parameter sweep leaves a quantity sampled over a grid of two knobs — a
device current over a `(Vgs, Vds)` grid, a gain over an `(R, C)` grid, a noise
figure over a `(freq, bias)` grid. The natural way to see it is a **contour
map**. E-218 adds a `-contour` flag to the `pyplot` command
([E-94](Enhancement-94.md)) that renders a filled contour of a quantity `z` over
the `(x, y)` plane.

```
pyplot -contour i(vd) vgs vds          # a device current over a (Vgs, Vds) grid
pyplot -contour gain rval cval         # a gain surface over an (R, C) grid
pyplot mymap -contour p x y            # named output (mymap.py/.data/.png)
```

The three arguments are the **height/colour** (`z`) and the two **axes** (`x`,
`y`), each a flattened, equal-length sweep vector.

## How it works

`-contour` is a render *mode*, like `-hist` ([E-217](Enhancement-217.md)) — it
is dispatched over the ordinary signal list rather than being a new analysis. So
it reuses the existing pyplot plumbing:

- **`com_pyplot`** detects the `-contour` marker anywhere in the argument list,
  unlinks it, and dispatches the remaining `[name] z x y` to `plotit` with a
  distinct device string, `pyplotcontour`.
- **`plotit`** resolves the three expressions exactly as for a normal plot (so
  `v(out)`, `db(...)`, arithmetic on vectors, node names all work) into a
  three-vector list (`z` first, then `x`, then `y`).
- **`ft_pyplot_contour`** writes an `(x, y, z)` data table and a matplotlib
  script that **triangulates** the `(x, y)` points (`ax.tricontourf`). Because
  the plane is triangulated rather than reshaped into a rectangular mesh,
  **gridded or scattered** sweep data plots identically — no grid-dimension
  metadata (`nx`, `ny`) is needed, and a sweep with a ragged tail still works.

Everything the `pyplot` family already offers carries over: the headless
`set pyplot_terminal=png|svg|pdf` render, style sheets, figure size, and backend
selection. Three contour-specific knobs are added:

- `set pyplot_contour_levels=<N>` — number of contour levels (default: matplotlib
  chooses);
- `set pyplot_contour_lines` — overlay labelled black contour lines on the filled
  map;
- `set pyplot_contour_cmap=<name>` — the colormap (default `viridis`).

The colorbar is labelled with `z`'s name and the axes with `x`'s and `y`'s.

### Robustness

- **Wrong argument count.** `-contour` needs exactly three vectors; anything else
  is rejected with a clear message (`pyplot -contour needs exactly three vectors:
  <z> <x> <y>`), not a confused plot.
- **A degenerate (1-D) sweep.** Triangulating collinear points is impossible; the
  generated script catches the failure and exits with a helpful line — *"a
  contour needs a genuine 2-D sweep (the points must not be collinear)"* —
  instead of a bare qhull/matplotlib traceback.

## Verification (`examples/pyplotcontour_examples`)

`pyplotcontour_demo.cir` builds a grid with a **closed-form** surface, so the
contour is checked analytically, not just rendered: `z = x² + y²` over
`x, y ∈ [-2, 2]` — a paraboloid whose contours are concentric circles, `z = 0` at
the centre and `z = 8` at the corners. `verify_pyplotcontour.py` (9 checks, both
solvers) parses the generated `.data`/`.py` and PNG and confirms: the `-contour`
path is taken (`tricontourf`, a colorbar labelled `z`, axes `x`/`y`); the data
table has **three** columns `(x, y, z)` for all `N = 1681` rows; the column
mapping is correct (`z` reconstructs `x² + y²` to 9e-16); the sweep is genuinely
2-D (`x` and `y` each span the full range, `z` runs from ~0 at the centre to 8 at
a corner); and a valid PNG is produced. Full regression: 178/178.

## Scope

ngspice only, four files (`frontend/com_pyplot.c`,
`frontend/plotting/pyplot.c` + `.h`, `frontend/plotting/plotit.c`). No change to
the ordinary `pyplot` trace path, `pyplot -hist`, or `pyplot -eye`.
