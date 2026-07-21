# `pyplot -smith` — Smith-chart plotting (Enhancement-254)

The second RF **design-aid**: a Smith-chart display for the matplotlib (`pyplot`)
path. ngspice's built-in plotter already has a `smith` grid, but the modern
`pyplot`/matplotlib output (the one that renders headless to PNG/SVG/PDF) had no
Smith mode — so reflection coefficients could not be viewed on a Smith chart in a
batch/scripted flow. `pyplot -smith` adds it, and is the display substrate the
stability/gain circles (E-255) plot onto.

```
pyplot [name] -smith <complex vectors>
```

Each vector (`S_1_1`, `S_2_2`, a load reflection `Γ`, a stability-circle trace, …)
is drawn as a curve in the reflection-coefficient plane (real part → x, imaginary
part → y) over the standard Smith grid:

- the unit circle `|Γ| = 1`,
- the constant-resistance circles (`r = 0.2, 0.5, 1, 2, 5`),
- the constant-reactance arcs (`x = ±0.2, ±0.5, ±1, ±2, ±5`), clipped to `|Γ| ≤ 1`.

Like the existing `-hist`/`-contour` modes it is a render mode over the normal
`pyplot` signal list, so all the usual `pyplot_*` settings apply
(`pyplot_terminal`, `pyplot_style`, `pyplot_figsize`, `pyplot_backend`). With
`set pyplot_terminal=png` it renders headless (Agg) to `<name>.png` and writes
`<name>.py`/`<name>.data`; otherwise it opens an interactive window.

```
.sp lin 201 10meg 6g 1
.control
run
pyplot input_match -smith S_1_1 S_2_2       * S11, S22 on the Smith chart
.endc
```

## Files

- `smith_demo.cir` — a resistive-capacitive two-port; `.sp` publishes `S_1_1 …
  S_2_2` vs frequency, then `pyplot -smith` draws S11/S22 (and a matched `Γ=0`
  load) on the Smith chart. Run it and open `smith_demo.png`.
- `verify_pyplotsmith.py` — the check below.

The generated `smith_demo.py`/`.data`/`.png`, `smith_match.png`, and `s11.dat` are
verify-run scratch (gitignored); the deck itself is left untouched.

## Verification

`verify_pyplotsmith.py` (both solvers; self-skips if matplotlib is unavailable)
runs `smith_demo.cir` and checks: `pyplot -smith S_1_1 S_2_2` renders a valid PNG;
the generated `.py` draws the Smith grid (unit circle + constant-R/X curves) and
both traces; the plotted data (`.data`) equals the S-parameters exactly (re, im
per point, to ~1e-7), so the curve on the chart is the true reflection
coefficient; and a matched coefficient (`Γ=0` → the chart center) renders without
error.

## Scope

Frontend plotting only (`frontend/plotting/pyplot.c` renderer, `plotit.c`
dispatch, `com_pyplot.c` `-smith` marker); the ngspice binary is rebuilt. No
solver, analysis, or numerical change — `pyplot -smith` is a display mode over
vectors a `.sp` (or Touchstone) run already produced.
