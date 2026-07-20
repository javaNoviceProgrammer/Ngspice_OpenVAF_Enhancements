# PWL code-model out-of-bounds read (Enhancement-246)

An out-of-bounds heap read in the XSPICE **`pwl`** and **`pwlts`** analog code
models, found by fuzzing code-model parameters and confirmed with
AddressSanitizer.

Both models take two independent vector parameters — `x_array` (breakpoint
abscissae) and `y_array` (ordinates) — and the XSPICE parameter framework
allocates each vector to its **own** length. At setup they size the working
table from `x_array` alone and then copy both arrays with that one index:

```c
size = PARAM_SIZE(x_array) + 2;
for (i = 1; i < size - 1; i++) {
    x[i] = PARAM(x_array[i - 1]);
    y[i] = PARAM(y_array[i - 1]);   /* indexed by the x_array length */
}
```

If `y_array` is **shorter** than `x_array`, `PARAM(y_array[i-1])` runs off the end
of the `y_array` parameter. AddressSanitizer pinpoints it:

```
ERROR: AddressSanitizer: heap-buffer-overflow ... READ of size 8
    #0 ... in cm_pwl   cfunc.c:321
    #0 ... in cm_pwlts cfunc.c:202
```

The read pulls adjacent / uninitialised heap into the interpolation table
(undefined behaviour; it can also crash outright once the mismatch is large
enough to run past the mapped heap). The sibling models `oneshot`
(`cntl_array` vs `pw_array`) and `multi_input_pwl` (`x` vs `y`) already guard this
with an equal-length check — `pwl`/`pwlts` predate that convention.

**Fix.** Add the same guard to both models: if
`PARAM_SIZE(x_array) != PARAM_SIZE(y_array)`, report a clean error and return
instead of reading out of bounds.

```
PWL: x_array and y_array must have the same length!
PWLTS: x_array and y_array must have the same length!
```

`verify_pwlfix.py` drives the repros under **both** solvers and asserts a valid
`pwl` still interpolates exactly (`in=0.5 -> 1.0 V`), a valid `pwlts` still runs,
and every length mismatch (either direction) is now rejected with a clean error
and no crash / OOB.

```
python3 verify_pwlfix.py
```

The code models load from the prebuilt bundle via `SPICE_LIB_DIR` (pointed at
`bin/<os>/<arch>/` by `_setup`); the test self-skips if that bundle is not
present in the checkout.

## Scope

XSPICE code models only (`xspice/icm/analog/pwl`, `.../pwlts`). No change to the
ngspice binary, the solver, or any analysis; valid equal-length `pwl`/`pwlts`
usage is unaffected.
