# table_model_examples — Verilog-A `$table_model` (Enhancement-16)

Demonstrates the `$table_model` lookup-table system function, using **version11's
own** `openvaf-r` and `ngspice-46`. `$table_model` interpolates a value from a
tabulated grid; the interpolation is **differentiable**, so it works in the main
device equations (its slope becomes the Jacobian conductance/capacitance).

| File | What it shows |
|---|---|
| `table_xfer.va` | Transfer function `V(out) = $table_model(V(in), '{x0,y0, x1,y1, ...})` — **inline** data array, constant (clamped) extrapolation. |
| `table_res.va` | Nonlinear resistor `I(p,n) = $table_model(V(p,n), "diode_iv.tbl", "1L")` — **file**-based data, linear extrapolation. |
| `diode_iv.tbl` | Two-column `V  I` data file for the nonlinear resistor. |
| `verify_table.py` | Compiles both, runs them through ngspice, checks interpolation and its derivative across **DC, AC and transient** against references. |
| `plot_table.py` | Runs the same simulations and writes the PNG plots below. |

## Plots

```
python3 plot_table.py
```

- **`table_dc.png`** — the interpolated transfer function `V(out)=table(V(in))` and
  the file-based I-V curve, with the tabulated grid points marked; shaded regions
  are the extrapolated ranges (clamped for the transfer table, linear for the I-V).
- **`table_ac.png`** — the AC small-signal conductance `g` vs bias lands exactly on
  the analytic piecewise-constant table slope `dI/dV` (the Jacobian the
  interpolation supplies).
- **`table_tran.png`** — a large-signal sine through the transfer table; `V(out)(t)`
  tracks `table(V(in)(t))` instantaneously (the piecewise-linear kinks appear as
  `V(in)` crosses the grid points).

## Run

```
python3 verify_table.py
```

Expected — the interpolation and its derivative are exercised across **DC, AC and
transient**:

```
transfer function (inline table, clamp)      max err 0.00e+00  PASS
DC: nonlinear op-point via table Jacobian    max err 4.8e-10 V  PASS
AC: small-signal g = table slope             max err 1.7e-18 S  PASS
Transient: V(out) tracks table(V(in))        max err 2.0e-08    PASS
ALL PASS
```

The derivative checks are the important ones. In **DC**, the nonlinear resistor is
driven through a series resistor, so ngspice solves `(vin - V)/Rs = I_table(V)` by
Newton iteration — converging to the analytic answer only because the table
supplies the correct per-segment slope `dI/dV` to the Jacobian. In **AC**, that
same slope is the small-signal conductance (it matches the analytic table slope
exactly at every bias). In **transient**, the table is re-evaluated each timestep
and `V(out)` tracks `table(V(in))` instantaneously. All three work identically
because `$table_model` lowers to plain differentiable MIR arithmetic.

## Usage & notes

```
out = $table_model(x, <data>[, "control"]);
```

- **`<data>`** is either an inline real array of flat `{x0,y0, x1,y1, ...}` pairs,
  or a data-file name (two whitespace-separated columns `x  y`; blank lines and
  `#`/`//`/`*` comments ignored, resolved relative to the source file). Points
  are sorted by `x`; duplicate abscissae are dropped.
- **Interpolation** is piecewise-**linear** (degree 1) and fully differentiable —
  usable directly in `V(...) <+` / `I(...) <+` contributions.
- **Extrapolation** outside the grid: **constant** (clamp to the endpoint value)
  by default; pass a control string containing `L` for **linear** extrapolation
  (the end segments' slopes continue). Constant clamping produces a zero slope
  outside the grid, so prefer `L` when the operating point can land there.
- Scope of this enhancement: **1-D** tables, linear interpolation. Multi-
  dimensional tables and higher-degree (spline) interpolation are natural
  follow-ups (as 1-D arrays in Enhancement-14 were extended to N-D in
  Enhancement-15).
