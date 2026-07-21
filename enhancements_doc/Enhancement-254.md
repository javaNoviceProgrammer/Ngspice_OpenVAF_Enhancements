# Enhancement-254 — `pyplot -smith`: Smith-chart plotting

The second of the RF **design-aid** additions (after `rfstab`, E-253). A Smith
chart is the working surface for two-port RF design — reflection coefficients,
matching-network trajectories, stability and constant-gain circles are all read
off it — but ngspice's modern matplotlib output (`pyplot`) had no Smith mode.
The legacy in-terminal plotter has a `smith` grid; the headless
`pyplot`/matplotlib path that renders to PNG/SVG/PDF in a scripted flow did not.
`pyplot -smith` adds it, and is the display substrate the stability/gain circles
(E-255) will plot onto.

## What it does

```
pyplot [name] -smith <complex vectors>
```

Each listed complex vector — `S_1_1`, `S_2_2`, a load reflection `Γ`, a
stability- or gain-circle trace — is drawn as a curve in the reflection-coefficient
plane (real part → x, imaginary part → y) over the standard Smith grid:

- the unit circle `|Γ| = 1` (the passive boundary);
- the constant-resistance circles `r = 0.2, 0.5, 1, 2, 5`
  (center `(r/(1+r), 0)`, radius `1/(1+r)`);
- the constant-reactance arcs `x = ±0.2, ±0.5, ±1, ±2, ±5`
  (center `(1, 1/x)`, radius `1/|x|`), clipped to `|Γ| ≤ 1`;
- the real (resistance) axis.

Like the existing `-hist` (E-217) and `-contour` (E-218) modes, `-smith` is a
render mode over the normal `pyplot` signal list — the marker is stripped and the
rest dispatched to the plotter's Smith device — so all the usual `pyplot_*`
settings apply (`pyplot_terminal`, `pyplot_style`, `pyplot_figsize`,
`pyplot_backend`). With `set pyplot_terminal=png` it renders headless (Agg) to
`<name>.png` and also writes `<name>.py`/`<name>.data`; otherwise it opens an
interactive window. The axes are set equal-aspect and framed to `|Γ| ≤ 1.08`.

## Usage

```
.sp lin 201 10meg 6g 1
.control
run
set pyplot_terminal=png
pyplot input_match -smith S_1_1 S_2_2     * S11 and S22 on one Smith chart
.endc
```

Any complex vector works, so a Touchstone-imported plot or a user-computed
reflection (`let gL = (zL-50)/(zL+50)`) can be overlaid on the same chart.

## Verification

`examples/pyplotsmith_examples/verify_pyplotsmith.py` (both solvers; self-skips if
matplotlib is unavailable) runs the shipped `smith_demo.cir` deck:

1. `pyplot smith_demo -smith S_1_1 S_2_2` renders a valid PNG (magic bytes) of
   non-trivial size;
2. the generated `smith_demo.py` draws the Smith grid (unit circle + constant-R/X
   curves) and plots both vectors;
3. the plotted data (`smith_demo.data`) equals the S-parameters exactly (re, im
   per point, to ~1e-7 vs a `wrdata` of `S_1_1`) — so the curve on the chart is
   the true reflection coefficient, not a re-scaled proxy;
4. a matched coefficient (`Γ = 0` → the chart center) renders without error
   (`smith_match.png`).

The generated `.py`/`.data`/`.png` and `s11.dat` are verify-run scratch
(gitignored); the tracked deck `smith_demo.cir` is left untouched.

## Scope

Frontend plotting only — the `ft_pyplot_smith` renderer in
`frontend/plotting/pyplot.c`, the `pyplotsmith` device dispatch in
`frontend/plotting/plotit.c`, and the `-smith` marker in `frontend/com_pyplot.c`;
the ngspice binary is rebuilt. No solver, analysis, or numerical change —
`pyplot -smith` is a display mode over vectors a `.sp` (or Touchstone) run already
produced. Full regression: all examples pass on both solvers.
