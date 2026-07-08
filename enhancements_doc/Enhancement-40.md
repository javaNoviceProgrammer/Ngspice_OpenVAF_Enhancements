# Enhancement-40 — N-dimensional `$table_model`

This document describes the changes made to **OpenVAF-r** in the `version11/`
directory to lift `$table_model`'s **3-dimension cap**: lookup tables of any
dimension now work. Purely front-end (`hir_ty` + `hir_lower`); no OSDI/ngspice
change.

## The gap

The question "are multi-dimensional tables supported?" verified out as: 1-D
(linear + cubic, inline + file), 2-D (bilinear + bicubic) and 3-D (trilinear)
all **exact** — but a 4-D call failed at the *signature* level:

```
error: invalid argument count: expected at most 2 arguments but found 6
```

The interesting part: the grid-file reader (`read_table_grid_nd`) and the
recursive multilinear interpolation (`interp_nd`) from Enhancement-17 were
**already fully dimension-general** — only the declared signature list
(explicit 1-D/2-D/3-D variants) and the signature-matched dispatch capped it.
The LRM sets no dimension bound.

## The fix

1. **`hir_ty`** — `TABLE_MODEL` becomes a **varargs** builtin (the listed 1-3-D
   signatures kept verbatim), and a dedicated `BuiltIn::table_model` arm in
   `infere_builtin` owns *every* call:
   - the 1-D inline-array form and small file forms resolve against the listed
     signatures unchanged;
   - N-D file forms (≥ 4 non-array arguments) get the exact signature
     `[Real × ndim, Literal(String)(, Literal(String))]` **synthesised from the
     argument shapes** — the trailing string literals are the data-file name and
     the optional control string, everything before them a coordinate.

   Owning all counts matters twice over: the generic varargs fallthrough
   *resizes* the listed signatures to the call's arity, which **truncates**
   longer signatures and made 2-argument calls ambiguous; and a 5-argument call
   is ambiguous *by arity alone* (3-D + file + ctrl vs 4-D + file) — the shape
   scan disambiguates it.

2. **`hir_lower`** — `lower_table_model` dispatches on argument **shapes**
   instead of the resolved signature (array second argument → 1-D inline;
   otherwise the first string literal marks the file, its index the dimension).
   `read_table_grid_nd` + `interp_nd` were already general; all partial
   derivatives continue to flow through `mir_autodiff` into the Jacobian.

The self-describing grid-file format is unchanged: `ndim`, axis sizes, each
axis's ascending coordinates, then row-major values (first axis slowest).

## Verification — `ndtable_examples/`

The demo grids hold **multilinear** functions, which multilinear interpolation
reproduces *exactly* at any off-grid point — so every check asserts analytic
equality. `verify_ndtable.py` (ALL PASS):

1. a **4-D** table compiles (used to error at the cap) and evaluates exactly at
   two off-grid points (`f4(1.5,0.25,0.75,0.4) = 7.9625`, second point
   parameter-swept);
2. **4-D without a control string** — the ambiguous 5-argument arity — resolves
   and evaluates exactly;
3. a **5-D** table with control string evaluates exactly (`6.5625`);
4. regression lock: the 1-D inline form still interpolates exactly.

Also exercised during development: 3-D exact (`9.36`), mixed per-dimension
control strings (`"3,1L"`). Regressions: all **36** version11 example verify
suites ALL PASS — including `table_model`/`mdtable`/`cubic_table`, which lock
the 1-3-D behaviour this change re-routes through the new dispatch.
