# Enhancement-142 — Input-frequency sweep for the two-tone small-signal analyses

QPAC (E-137), QPnoise (E-138/139) and QPXF (E-141) each computed the response at a
**single** input frequency and printed a table. This enhancement makes them **swept**
analyses over `f_in`, emitting an ngspice plot — conversion gain, noise figure and
image-rejection curves versus frequency — exactly the way `.ac` / `.pnoise` / `.pxf`
sweep.

```
qpac  <dec|oct|lin> <N> <fstart> <fstop>
qpnoise <output_node> <dec|oct|lin> <N> <fstart> <fstop>
qpxf    <output_node> <dec|oct|lin> <N> <fstart> <fstop>
```

The single-frequency forms are unchanged; a `dec`/`oct`/`lin` keyword in the sweep
position selects the swept form. The result is a normal ngspice plot (made current), read
back with `plot` / `print` / `setplot`.

## Method

Each swept point reuses the **exact same single-frequency solve** — so a swept value at a
given `f_in` equals the single-frequency result there. Around the retained QPSS operating
point the sweep steps `f_in` (geometric for dec/oct, linear for lin) and, per point:

- **`qpac`** — solves `H(f_in)·X = B0` and records the in-band `(0,0)` response magnitude
  for **every node** (one plot vector per node, like a pumped `.ac`);
- **`qpnoise`** — folds the device noise through the adjoint and records
  `onoise_spectrum` and `inoise_spectrum` (the two-tone noise-figure curve);
- **`qpxf`** — one adjoint solve per point, recording `xf` (the in-band `(0,0)` transfer)
  and `xf_conv` (the total conversion, `√Σ|H_{sb≠0}|²`).

The analysis fills plain arrays; the front-end builds the ngspice plot with a `frequency`
scale via the nutmeg vector API (`plot_alloc` / `dvec_alloc` / `vec_new`) — the correct
layer for a front-end command, rather than the analysis-job output framework (which needs
a live analysis job a front-end command does not have).

## Verification

`verify_qpss_sweep.py` (5/5), numpy-free:

- **qpac** — the swept `(0,0)` response at 0.3 GHz equals the single-frequency `qpac`
  `(0,0)` response to machine precision;
- **qpxf** — the swept `xf` at 0.3 GHz equals the single-frequency `qpxf` `(0,0)`;
- **qpnoise** — the swept `onoise` at 0.3 GHz equals the single-frequency `qpnoise`;
- **frequency dependence** — a reactive circuit's response rolls off with `f_in` (an RC
  low-pass), so the sweep is genuinely frequency-dependent, not a repeated constant;
- **point count** — a `lin N` sweep produces exactly `N` points.

The single-frequency suites are unaffected: QPAC 7/7, QPnoise 10/10, QPXF 6/6 (and QPSS
11/11, QPSS-HB 7/7).

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/dcpss.c` | `QPACsweep` / `QPnoiseSweep` / `QPXFsweep` — step `f_in`, reuse the single-frequency solve, fill caller arrays (`freqs[]` + point-major `data[]`) |
| `ngspice-46/src/frontend/com_qpac.c` / `.h` | shared sweep helpers — `qp_steptype` (dec/oct/lin), `qp_sweep_maxpts`, and `qp_emit_plot` (builds the ngspice plot) |
| `ngspice-46/src/frontend/com_qpnoise.c`, `com_qpxf.c`, `commands.c` | detect the sweep keyword, allocate, call the sweep, emit the plot; help strings |
| `ngspice-46/src/include/ngspice/cktdefs.h` | swept-analysis prototypes |
| `examples/qpss_examples/verify_qpss_sweep.py` | the 5-check sweep suite |

## Scope

`dec`/`oct`/`lin` input-frequency sweep of the two-tone small-signal analyses, emitting
plottable ngspice curves that match the single-frequency solves point-for-point. This
makes the quasi-periodic small-signal suite production-grade for conversion-gain / noise-
figure / image-rejection plots. Follow-ups: a swept cyclostationary `qpnoise`, and
per-sideband vectors for `qpac`/`qpxf` (currently the in-band response plus the total
conversion).
