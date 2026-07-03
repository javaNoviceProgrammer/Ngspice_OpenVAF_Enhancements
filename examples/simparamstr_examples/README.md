# simparamstr_examples — `$simparam$str(name)` (Enhancement-25)

Demonstrates **`$simparam$str(name)`**, which returns a *string* simulator
parameter, using **version11's own** `openvaf-r` and `ngspice-46`. Previously it
was unusable — three separate defects: the builtin was mis-typed as returning a
**real**, the runtime lookup was **bugged** (it walked the numeric parameter list
and returned the *name* instead of the value), and ngspice exposed **no** string
parameters at all.

## What it does now

ngspice provides two string simulator parameters:

- **`"analysis_name"`** — `"dc"` / `"ac"` / `"tran"` / `"noise"` (same naming as
  the `analysis()` function), derived from the current analysis mode;
- **`"simulator"`** — `"ngspice"`.

They can be read into a `string` variable, compared, and used to branch on the
current analysis, e.g.:

```verilog
string an;
an = $simparam$str("analysis_name");
if (an == "tran") ... else ...
```

## The model

`simparamstr_demo.va` sets its conductance from `$simparam$str("analysis_name")`:
`g_dc` in dc/op, `g_ac` in ac, `g_tran` in tran.

## Run

```
python3 verify_simparamstr.py
```

Expected (`ALL PASS`): running each analysis and checking the terminal current
confirms the correct string is returned in dc, ac, and tran.

## Notes / limitations

- Requires the accompanying **ngspice** change (`OSDIload` in `src/osdi/`), so it
  only works with version11's rebuilt `ngspice`.
- The provided string parameters are `"analysis_name"` and `"simulator"`; an
  unknown name raises a fatal "unknown $simparam_str" (as for the numeric
  `$simparam` with no default).
- The numeric `$simparam(name[, default])` was already supported and is
  unchanged.
