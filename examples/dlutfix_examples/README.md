# d_lut / d_genlut undefined-behaviour shift (Enhancement-250)

An undefined-behaviour left shift in the XSPICE digital lookup-table code models
**`d_lut`** and **`d_genlut`**, found with UndefinedBehaviorSanitizer.

Both models size their table as `2^(number of inputs)`, computed with a left
shift of the input-port count:

```c
size     = PORT_SIZE(in);      /* d_lut    */
tablelen = 1 << size;

isize    = PORT_SIZE(in);      /* d_genlut */
entrylen = (1 << isize);
```

The input-port count was never bounded. A left shift of a 32-bit `int` by `>= 32`
is **undefined behaviour**:

```
d_lut/cfunc.c:146:18: runtime error: shift exponent 32 is too large for 32-bit type 'int'
```

and a count in the high twenties asks for a multi-gigabyte table allocation. Both
are reachable from a valid-syntax netlist — an `a`-device with ~30+ digital
inputs fanned into the LUT (e.g. all tied to one pulled-up net).

**Fix.** Cap the input-port count at `D_LUT_MAX_INPUTS` / `D_GENLUT_MAX_INPUTS`
(24 — a real lookup table has only a handful of inputs) *before* the shift,
reporting a clean error instead of the UB / oversized allocation.

`verify_dlutfix.py` (4 checks, both solvers): valid 2-input `d_lut` and
`d_genlut` still simulate; a 32-input `d_lut` and a 32-input `d_genlut` are each
rejected with a clean "out of range" error and no crash.

```
python3 verify_dlutfix.py
```

The code models load from the prebuilt bundle via `SPICE_LIB_DIR` (pointed at
`bin/<os>/<arch>/` by `_setup`); the test self-skips if that bundle is absent.

## Scope

XSPICE code models only (`xspice/icm/digital/d_lut`, `.../d_genlut`). Fix is in
`.cm` code models, so `digital.cm` is rebuilt; the ngspice binary is unchanged.
No solver, analysis, or numerical change; a normal LUT (a handful of inputs) is
unaffected.
