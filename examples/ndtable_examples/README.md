# ndtable_examples — N-dimensional `$table_model` (Enhancement-40)

Demonstrates `$table_model` lookup tables of **any dimension** (the 3-D cap
lifted), using **the committed** `openvaf-r` and `ngspice-46`.

## What was broken

A 4-D `$table_model` call failed at the signature level (`expected at most 2
arguments but found 6`) — even though the grid reader and the recursive
multilinear interpolation (Enhancement-17) were already fully dimension-general.
Only the hard-coded 1/2/3-D signature list and the signature-matched dispatch
capped it; the LRM sets no bound.

## The fix

`$table_model` is variadic: N-D file forms get their exact
`[Real × ndim, "file"(, "ctrl")]` signature synthesised from the argument
shapes, and the lowering derives the dimension by scanning for the data-file
argument — which also resolves the 5-argument arity ambiguity
(3-D + file + ctrl vs 4-D + file) by shape. The self-describing grid-file format
is unchanged, and all partial derivatives still flow into the Jacobian via
autodiff. See `../Enhancement-40.md`.

```verilog
val = $table_model(x, y, z, w, "grid4.tbl", "1L");        // 4-D
val = $table_model(a, b, c, d, e, "grid5.tbl", "1L");     // 5-D ...
```

## Run

```
python3 verify_ndtable.py
```

Checks (ALL PASS): 4-D compiles (used to error) and is **analytically exact** at
off-grid points (the grids hold multilinear functions, reproduced exactly by
multilinear interpolation); the ambiguous 5-argument arity (4-D, no control)
resolves; 5-D exact; the 1-D inline form regression-locked.
