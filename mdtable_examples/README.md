# mdtable_examples — multi-dimensional `$table_model` (Enhancement-17)

Demonstrates **multi-dimensional** `$table_model` (2-D bilinear), using
**version11's own** `openvaf-r` and `ngspice-46`. Enhancement-17 generalises the
1-D lookup tables of Enhancement-16 to any number of dimensions (1-D / 2-D / 3-D)
via **multilinear** interpolation — still differentiable, so every partial
derivative feeds the Jacobian.

`mos_table.va` is a **table-based MOSFET**: its drain current is a 2-D lookup
table `I(Vgs, Vds)` read from `mos_iv.tbl`, interpolated bilinearly:

```
I(d, s) <+ $table_model(V(g, s), V(d, s), "mos_iv.tbl", "1L");
```

| File | Purpose |
|---|---|
| `mos_iv.tbl` | Self-describing 2-D grid: `ndim`, axis sizes, axis coordinates, then row-major values. |
| `mos_table.va` | The table-based MOSFET. |
| `verify_mdtable.py` | Checks DC current and the AC `gm`/`gds` against a bilinear reference. |
| `plot_mdtable.py` | Output characteristics + the interpolated `I(Vgs, Vds)` surface → `mdtable_iv.png`. |

## Run

```
python3 verify_mdtable.py     # DC + AC checks
python3 plot_mdtable.py       # writes mdtable_iv.png
```

Expected:

```
DC: 2-D I(Vgs,Vds) vs bilinear reference       max err ~1e-19 A  PASS
AC: gm, gds vs bilinear partials               max err ~1e-16 S  PASS
```

The AC check is the important one: the two partial derivatives of the bilinear
surface — transconductance `gm = dId/dVgs` and output conductance
`gds = dId/dVds` — both come out **exact**, i.e. the full 2-D Jacobian is correct.

## The grid file format

For 2-D and 3-D, the data is a **self-describing grid file** (whitespace-separated
tokens; blank lines and `#`/`//`/`*` comments ignored):

```
2                 # number of dimensions
6 6               # grid size along each axis
0 0.4 ... 2.0     # axis-0 (Vgs) coordinates, ascending
0 0.4 ... 2.0     # axis-1 (Vds) coordinates, ascending
<v ...>           # size0*size1 values, row-major (axis-0 slowest)
```

## Notes

- **Interpolation** is **multilinear** (bilinear in 2-D, trilinear in 3-D), built
  as recursive 1-D interpolation, and fully differentiable — usable directly in
  `V(...) <+` / `I(...) <+` contributions across DC, AC and transient.
- **Extrapolation** outside the grid is per-axis **constant** (clamp) by default,
  or **linear** with a control string containing `L` (as here).
- 1-D still takes an inline `'{x0,y0,...}` array or a two-column data file
  (Enhancement-16); 2-D/3-D take one coordinate per dimension and a grid file.
- Supported dimensionality is **1-D, 2-D and 3-D** — the practical range for
  compact-model tables. Higher-degree (spline) interpolation remains future work.
