# Enhancement-16 — Verilog-A `$table_model`

This document describes the source-code changes made to **OpenVAF-r** in the
`version11/` directory to implement the Verilog-AMS **`$table_model`** lookup-table
system function (1-D), which previously carried an explicit `// TODO TABLE_MODEL`
in the builtin signature table and was rejected as *"not found in the current
scope"*.

`$table_model(x, <data>[, "control"])` interpolates a value from a tabulated
grid. Unlike the E-9 `noise_table` (which feeds only the noise PSD path),
`$table_model` is used in the **main device equations**, so the interpolation
must be **differentiable** — its slope becomes the Jacobian entry. It is verified
end-to-end through ngspice (see `examples/table_model_examples/`).

All work is in `version11/`; verification uses `version11/ngspice-46`'s own
binary and `version11/OpenVAF-master`'s own `openvaf-r`. **No OSDI ABI change and
no ngspice change were needed** — the table is read at compile time and lowered
to ordinary differentiable MIR arithmetic.

## Design: lower to differentiable MIR (no special autodiff support)

The key decision is to lower `$table_model` to **plain MIR arithmetic** — a
piecewise-linear interpolation built as a select chain over the compile-time
grid — rather than to a special callback. Because `mir_autodiff` differentiates
ordinary arithmetic, this gives the correct per-segment slope `dy/dx` as the
Jacobian entry **for free**, exactly as the Enhancement-14/15 dynamic-index
select chains do. `$table_model` is therefore an ordinary **pure** function (not
an analog operator with state/time), classified `is_analog_operator() == false`.

## 1. Wiring the builtin

- **`hir_def::builtin`** — `BuiltIn::table_model = 111` added; the pre-existing
  `sysfun::table_model` name (`$table_model`, already tokenized) is registered:
  `dst.insert(sysfun::table_model, BuiltIn::table_model.into())`. It is a pure
  function, so the classification predicates leave it at their `_ => false`
  defaults.
- **`hir_ty::builtin`** — the `TODO TABLE_MODEL` is replaced by a `TABLE_MODEL`
  signature group (four 1-D variants: inline-array vs data-file × with/without a
  control string). The generated `BUILTIN_INFO` table gains the `TABLE_MODEL`
  entry (length 111 → 112).

## 2. Reading the table (compile time)

`table_model_data` gathers the `(x, y)` points — from an inline real array of
flat `{x0,y0, x1,y1, ...}` pairs (const-folded via `eval_const_real`) or from a
two-column data file (reusing E-9's `read_noise_table_file`; blank/comment lines
skipped, path relative to the source file). Points are sorted by `x` and
duplicate abscissae dropped so the segments are well-formed.

## 3. Lowering the interpolation (`lower_table_model`)

For a grid of `N` points, each segment `i` contributes the linear value
`y_i + (x - x_i)·slope_i` (slope folded to a constant at compile time). These are
combined into a select chain: segment `i` becomes active once `x >= x_i`
(segment 0 is the default and also covers `x` below the grid; the last segment
covers `x` above it). This yields linear interpolation inside the grid and, by
default, **linear extrapolation** from the end segments.

The control string selects extrapolation: it defaults to **constant** (the value
is clamped to the endpoint outside the grid, via two extra `select`s), or
**linear** when the string contains `L`. The comparison-driven `select`s make the
result piecewise-linear and differentiable; `mir_autodiff` follows the active
branch, so the Jacobian entry is the local segment slope (zero in a clamped
region — hence prefer `L` where the operating point may leave the grid).

## Verification

- `examples/table_model_examples/verify_table.py` exercises the value **and its derivative**
  across **DC, AC and transient**:
  - **DC** — an inline-array transfer function `V(out) = $table_model(V(in), '{...})`
    matches a reference piecewise-linear interpolation **bit-exactly**; and a
    file-based nonlinear resistor `I(p,n) = $table_model(V(p,n), "diode_iv.tbl",
    "1L")` driven through a series resistor converges to the analytic nonlinear DC
    operating point (~5e-10 V) — only possible because the interpolation supplies
    the correct `dI/dV` to the Jacobian;
  - **AC** — that same slope is the small-signal conductance: it matches the
    analytic table slope exactly at every bias point (error ~1e-18 S);
  - **Transient** — the table is re-evaluated each timestep and `V(out)` tracks
    `table(V(in))` instantaneously (~2e-8 over the sweep).

  All three work identically because `$table_model` lowers to plain differentiable
  MIR: the value flows into the residual and its autodiff derivative into the
  Jacobian, which DC Newton, the AC linearization, and each transient step all use.
- The `hir_def`/`hir_ty`/`hir`/`hir_lower` unit-test suites pass with no
  regressions; `noise_examples` (the closest existing code) and every other prior
  example still pass. The pre-existing stale `sim_back` snapshot failures are
  unchanged and unrelated.

## Known limitations / future work

- **1-D only**, **linear** interpolation. Multi-dimensional tables
  (bilinear/trilinear) and higher-degree (spline) interpolation are the natural
  next step — the same way Enhancement-14's 1-D arrays were generalised to N-D in
  Enhancement-15.
- The control string is interpreted leniently (degree is always 1; presence of
  `L` ⇒ linear extrapolation on both ends, otherwise constant), rather than the
  full per-dimension LRM control-string grammar.
- The data-file format is the simple two-column form shared with `noise_table`,
  not the full Verilog-AMS `$table_model` file grammar.
