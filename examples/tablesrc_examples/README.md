# tablesrc_examples — `$table_model` data from arrays, `I`, the quadratic spline, `localparam string` names (Enhancement-562)

The lookup-table gaps the
[coverage audit of *A Practical Guide to Verilog-A*](../../docs/audits/2026-09-05_practical-guide-verilog-a-coverage.md)
§3.5 recorded, closed and pinned through **the committed** `openvaf-r` and
`ngspice-46`, both solvers.

## What was missing

* The **LRM 9.21.1 array data source** for a table of two or more dimensions:
  `$table_model(yy, xx, y, x, f)` with one 1-D array per column, or
  `$table_model(yy, xx, tab)` with one 2-D array whose rows are the columns. The
  book fills the column arrays in an `analog initial` block. Only the 1-D
  runtime pair `(x, xs, ys)` existed; anything else was *'y' requires a
  bit-select [i]*.
* A **string parameter** as the file name or the control string
  (`file_name ::= string_literal | string_parameter`): *type mismatch*.
* Table 9-30's **`I`** (ignore this data column) and **`2`** (quadratic
  spline): *unsupported control string*.

## What the models show

| model | construct | check |
|---|---|---|
| `tablesrc_cols.va` | column arrays `y`, `x`, `f` filled in `analog initial`; f = 2x + y on ragged isolines | exact at five points, two of them extrapolated |
| `tablesrc_matrix.va` | one 2-D array `tab[0:2][0:10]`, rows = columns | the same five values |
| `tablesrc_locparam.va` | `localparam` arrays, `localparam string ctl`, `localparam string fname` for the file form | 2·(2x + y) |
| `tablesrc_ignore.va` | `"I,1L,1L"` on a four-column file, `"I,1,1"` on four arrays (the first a tag) | 2·(2x + y) |
| `tablesrc_quad.va` | `"2L"` / `"2C"` on inline `'{...}` data and on runtime arrays, knots x² at 0..3 | equal to an independent Python evaluation of the spline, inside and outside the grid |
| `tablesrc_capture.va` | a knot computed from `V(a,b)` in the run-time array form, the call site optionally under a condition the initial guess fails | captured at the first evaluation (LRM 9.21.1): one table `{0, 1, 4}` for a whole `dc` sweep, the compiler's L038 warning; a gated call site captures at the first evaluation that reaches it and afresh in the next analysis |
| `tablesrc_recapture.va` | knots from an instance parameter and `$temperature`, the call site optionally gated the same way | left live (its data cannot change between two setups): follows every sweep point and `alter`, no warning |
| `refused/*.va` | overridable `parameter string` (control, file name), overridable `parameter` array, an array written under a condition, `I` on runtime arrays, `I` on inline data, a wrong array shape | each refused with the named diagnostic |

The array form is read **when the model is compiled**, exactly as a data file
is, so its arrays must be compile-time constants: a declaration initialiser, a
`localparam` array, or one straight-line assignment (in `analog initial`,
`@(initial_step)` or the analog block itself) of a literal or a `localparam`.
Anything else is refused with the reason, and the message points at the 1-D
runtime form for data computed at run time.

The quadratic spline is the C1 construction with knot slopes `z_0 = s_0`,
`z_{i+1} = 2 s_i − z_i` (`s_i` the chord slopes); each interval is
`v_i + z_i·dx + (z_{i+1} − z_i)/(2h_i)·dx²`, and `L` continues the end tangents.

## Run

```
python3 verify_tablesrc.py
```

A data file the call cannot use is refused with its cause named since
[E-700](../../enhancements_doc/Enhancement-700.md): `refused/short_columns.va`
hands two inputs a two-column file and reads "its rows have 2 columns, but the
call has 2 inputs and needs at least 3" (it read "missing, unreadable, or
contains no usable table data", under notes about non-finite values).

Since [E-702](../../enhancements_doc/Enhancement-702.md) the run-time array
form captures its data at the instance's first evaluation of each analysis, as
LRM 9.21.1 says ("captured on the first call ... any change after this point is
ignored"): a knot computed from `V(a,b)` makes one table for a whole sweep,
where it used to make a different table at every Newton iterate, and the
compiler warns (L038, `table_data_captured`) that the dependence never reaches
the table. A table whose data comes from parameters, constants, the
temperature or an `@(initial_step)` fill is not captured at all: it cannot
change between two setups, and ngspice sets the instance up again at every
analysis start, sweep point and `alter`, so it is left live and keeps its
compile-time folding.

57 checks per solver, all PASS.
