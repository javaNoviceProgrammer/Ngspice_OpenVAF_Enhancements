# Enhancement-250 — undefined-behaviour shift in `d_lut` / `d_genlut`

An undefined-behaviour left shift in the XSPICE digital lookup-table code models
`d_lut` and `d_genlut`, found with UndefinedBehaviorSanitizer while sweeping the
XSPICE code-model library (the same dive as E-240/E-246/E-247).

## The bug

Both models size their lookup table as `2^(number of inputs)`, computed with a
left shift of the connected-input-port count:

```c
size     = PORT_SIZE(in);      /* d_lut,   cfunc.c:143-144 */
tablelen = 1 << size;

isize    = PORT_SIZE(in);      /* d_genlut, cfunc.c:154/177 */
entrylen = (1 << isize);
```

The port count was never bounded. A left shift of a 32-bit `int` by an amount
`>= 32` is **undefined behaviour**, which UBSan flags exactly:

```
d_lut/cfunc.c:146:18: runtime error: shift exponent 32 is too large for 32-bit type 'int'
SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior d_lut/cfunc.c:146:18
```

Even short of that, a count in the high twenties (`1 << 28` …) asks for a
multi-gigabyte table allocation. Both are reachable from a valid-syntax netlist —
an `a`-device with ~30+ digital inputs fanned into the LUT (e.g. all tied to one
pulled-up net). On the release build the UB happens to be benign on arm64 (the
shift amount is taken mod 32, so `1 << 32` yields 1 and no crash) — which is
exactly why it is worth fixing: the table size is silently *wrong* rather than
loud.

## The fix

Cap the input-port count *before* the shift:

```c
#define D_LUT_MAX_INPUTS 24     /* a real LUT has only a handful of inputs */
...
size = PORT_SIZE(in);
if (size < 1 || size > D_LUT_MAX_INPUTS) {
    cm_message_send("d_lut: number of input ports out of range "
                    "(must be 1..24); the 2^n lookup table would be too large");
    return;
}
tablelen = 1 << size;
```

`d_genlut` gets the identical guard (`D_GENLUT_MAX_INPUTS`). 24 keeps `1 << n`
well inside `int` and bounds the table, while being far above any realistic LUT
(the `table_values` string is `2^n` characters, so even a dozen inputs is
already unwieldy).

## Verification

`examples/dlutfix_examples/verify_dlutfix.py` (4 checks, both solvers): valid
2-input `d_lut` and `d_genlut` still simulate; a 32-input `d_lut` and a 32-input
`d_genlut` are each rejected with a clean "out of range" error and no crash. The
`1 << 32` undefined behaviour was reproduced under a UBSan build of the code
models (`shift exponent 32 is too large`) and shown fixed.

## Scope

XSPICE code models only (`xspice/icm/digital/d_lut`, `.../d_genlut`). Fix is in
`.cm` code models, so `digital.cm` is rebuilt and redeployed under
`bin/*/codemodels/`; the ngspice binary is unchanged. No solver, analysis, or
numerical change; a normal LUT is unaffected. Full regression: all examples pass.
