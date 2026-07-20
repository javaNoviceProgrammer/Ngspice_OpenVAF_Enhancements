# Enhancement-246 — out-of-bounds read in the `pwl` / `pwlts` code models

An out-of-bounds heap read in two XSPICE analog code models, found by fuzzing
code-model parameters and confirmed with AddressSanitizer. This is the second
find inside the XSPICE code-model library (after E-240's `s_xfer`); both models
predate the length-check convention their siblings already follow.

## The bug

`pwl` (`xspice/icm/analog/pwl/cfunc.mod`) and `pwlts`
(`xspice/icm/analog/pwlts/cfunc.mod`) each take two independent vector
parameters — `x_array` (breakpoint abscissae) and `y_array` (ordinates). The
XSPICE parameter framework allocates each vector parameter to its **own** length;
nothing ties the two lengths together. At setup the models size their working
table from `x_array` only, then copy both arrays with that single index:

```c
size = PARAM_SIZE(x_array) + 2;
...
for (i = 1; i < size - 1; i++) {
    x[i] = PARAM(x_array[i - 1]);
    y[i] = PARAM(y_array[i - 1]);   /* <- indexed by the x_array length */
}
```

When `y_array` is **shorter** than `x_array`, `PARAM(y_array[i-1])` reads past the
end of the `y_array` parameter allocation. AddressSanitizer flags it exactly:

```
==...==ERROR: AddressSanitizer: heap-buffer-overflow ... READ of size 8 ...
    #0 ... in cm_pwl   cfunc.c:321
    #1 ... in MIFload  mifload.c:447
    ...
SUMMARY: AddressSanitizer: heap-buffer-overflow cfunc.c:321 in cm_pwl
```

```
SUMMARY: AddressSanitizer: heap-buffer-overflow cfunc.c:202 in cm_pwlts
```

The overflow pulls adjacent / uninitialised heap into the interpolation table —
undefined behaviour that silently corrupts the transfer characteristic, and can
crash outright once the mismatch is large enough to run past the mapped heap. It
is reachable from any netlist with such an a-device, for example:

```
A1 in out mod
.model mod pwl(x_array=[0 0.25 0.5 0.75 1 1.5 2 2.5] y_array=[0 1])
```

The sibling models already guard this: `oneshot` checks `cntl_size != pw_size`
and `multi_input_pwl` checks `PARAM_SIZE(x) != PARAM_SIZE(y)`. `pwl`/`pwlts` — the
oldest PWL models — never got the check.

## The fix

Add the same equal-length guard to both models, before the `x_array`-sized
allocation and copy loop:

```c
if (PARAM_SIZE(x_array) != PARAM_SIZE(y_array)) {
    cm_message_send(size_error);
    return;
}
```

`size_error` is a clear message (`"PWL: x_array and y_array must have the same
length!"` / `"PWLTS: ..."`), and the early `return` aborts model setup cleanly —
exactly as `oneshot` does for its own mismatch — instead of reading out of bounds.
Equal-length `pwl`/`pwlts` usage is completely unaffected.

## Verification

`examples/pwlfix_examples/verify_pwlfix.py` (5 checks, both solvers):

1. a valid `pwl` still interpolates exactly — `x=[-1 0 1 2]`, `y=[-1 0 2 3]`,
   input `0.5 V` → `1.0 V` output;
2. `pwl` with `x_array` longer than `y_array` (the OOB case) now reports the size
   error and does not crash;
3. `pwl` with `y_array` longer than `x_array` is likewise rejected cleanly;
4. a valid `pwlts` time-series source still runs;
5. `pwlts` with mismatched lengths reports the size error and does not crash.

The out-of-bounds read itself was reproduced and then shown fixed under an
AddressSanitizer build of the code models (`heap-buffer-overflow` at
`cfunc.c:321` / `cfunc.c:202` before the fix; a clean size error after).

Full regression (both solvers): all examples pass.

## Scope

XSPICE code models only (`xspice/icm/analog/pwl`, `.../pwlts`). The ngspice
binary itself is unchanged — only the prebuilt `analog.cm` bundle is rebuilt. No
solver, analysis, or numerical change; valid equal-length usage is unaffected.
