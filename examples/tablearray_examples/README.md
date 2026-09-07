# tablearray_examples — `$table_model` from arrays, into variables, inside analog functions

A pin written on 2026-09-07 after the question "can the table feature interpolate an
array of data?" was answered by probing the committed `openvaf-r` and `ngspice-46`, both
solvers. Nothing had to change; this suite keeps the answer true. Every table holds the
same grid, y = x² at x = 0, 1, 2, 3, so the expected values are the same throughout:
2.5 for linear interpolation at 1.5, 2.2 for the natural cubic spline, 11.5 for linear
extrapolation at 3.5, and a slope of 3 at 1.5 for both kinds.

| file | what it pins |
|---|---|
| `rt_lin.va`, `rt_cub.va` | array variables filled in the analog block from a model parameter (E-389), read with `"1L"` and with the natural cubic spline `"3L"`; `altermod` of the parameter rebuilds the table |
| `par_arr.va` | `parameter real xs[0:3]`, `ys[0:3]` handed to `$table_model` as they are |
| `lit_pair.va` | an inline pair of array literals, `'{xs}, '{ys}` |
| `col2d.va` | the LRM 9.21.1 column-array form of a 2-D table from `localparam` arrays (E-562), z = x·y, which bilinear interpolation reproduces exactly |
| `var_lit.va` | the result assigned to a variable: `y` is read back as an operating-point variable, a second cubic runtime-array table into `y2`, and the AC conductance shows both slopes survived the assignment |
| `fn_lit.va`, `fn_file.va`, `fn_arg.va`, `fn_loc.va` | `$table_model` inside an analog function: literal arrays, the data file `sq.tbl`, arrays passed in as function arguments (E-18), arrays filled locally in the function body; value and AC slope each |
| `refused/col2d_param.va` | the N-D array form from an overridable `parameter` array is refused, and the message says to declare it `localparam` |

The run-time array form is 1-D only and capped at 256 knots (E-392); the abscissae are
sorted and de-duplicated before interpolation (E-390, E-391). The N-D array form is read
when the model is compiled, like a data file, so its arrays must be compile-time constants.

## Run

```
python3 verify_tablearray.py
```

29 checks per solver, all PASS.
