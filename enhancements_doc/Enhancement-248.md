# Enhancement-248 — out-of-bounds accesses in the CPL coupled-line device

Two out-of-bounds accesses in the **CPL** coupled multiconductor transmission
line (`p` device, model type `cpl`), found by fuzzing the conductor count and the
R/L/C/G matrix sizes and confirmed with AddressSanitizer / UndefinedBehaviorSanitizer.
Unlike the recent XSPICE code-model finds (E-240/E-246/E-247), this is a **core**
ngspice device — compiled into the simulator binary.

## Background

A CPL line has `noL` conductors. `noL` (the instance's `dimension`) is set from
the node count on the `p` card. Each of the symmetric R/L/C/G matrices is supplied
as its upper triangle — `noL*(noL+1)/2` values, e.g. a 2-conductor line takes
three each (`R11 R12 R22`). `CPLsetup` / `ReadCpL`
(`spicelib/devices/cpl/cplsetup.c`) validated neither the conductor count nor the
matrix lengths.

## The bugs

### 1. Under-specified matrix — heap OOB read

`ReadCpL` fills the working matrices from the model arrays:

```c
counter = 0;
for (i = 0; i < noL; i++)
    for (j = 0; j < noL; j++)
        if (i > j) { R_m[i][j] = R_m[j][i]; ... }
        else {
            f = CPLmodPtr(here)->Rm[counter];      /* cplsetup.c:474 */
            ... = CPLmodPtr(here)->Gm[counter];
            ... = CPLmodPtr(here)->Lm[counter];
            ... = CPLmodPtr(here)->Cm[counter];
            counter++;
        }
```

`counter` runs `0 .. noL*(noL+1)/2 - 1`, but `Rm`/`Lm`/`Cm`/`Gm` are allocated to
the number of values the user actually gave (`Rm_counter`, …). Supplying fewer
values than the triangle needs reads past the end:

```
ERROR: AddressSanitizer: heap-buffer-overflow ... READ of size 8
    #0 ... in ReadCpL cplsetup.c:474
```

### 2. Too many conductors — fixed-array overflow

`ReadCpL` uses `RLINE *lines[MAX_CP_TX_LINES]` and, in the `CPLine` structure,
`in_node[MAX_CP_TX_LINES]` / `out_node[MAX_CP_TX_LINES]`, with
`MAX_CP_TX_LINES == 8` (`include/ngspice/swec.h`). Those arrays are indexed by
`noL`, so a `p` card with more than 8 conductors writes past them:

```
UndefinedBehaviorSanitizer: index 8 out of bounds for type 'NODE *[8]'
    cplsetup.c:430
```

Both are reachable from a valid-syntax netlist (a `p` line with too few matrix
entries, or with more than 8 conductors). On the release binary the reads pull
adjacent heap — heap-layout-dependent garbage that here happens to trip a
downstream "fatal error" exit, but could equally produce wrong results or crash.

## The fix

Validate both up front in `CPLsetup`, immediately after `noL = here->dimension`
and before any allocation:

```c
int need = noL * (noL + 1) / 2;
if (noL < 1 || noL > MAX_CP_TX_LINES) {
    SPfrontEnd->IFerrorf(ERR_FATAL, "%s: coupled line has %d conductors; the "
        "number of conductors must be between 1 and %d",
        here->CPLname, noL, MAX_CP_TX_LINES);
    return(E_BADPARM);
}
if (model->Rm_counter < need || model->Lm_counter < need ||
    model->Cm_counter < need || model->Gm_counter < need) {
    SPfrontEnd->IFerrorf(ERR_FATAL, "%s: a %d-conductor coupled line needs %d "
        "entries (upper triangle) in each of R, L, C and G; got "
        "R=%d L=%d C=%d G=%d", here->CPLname, noL, need,
        model->Rm_counter, model->Lm_counter, model->Cm_counter, model->Gm_counter);
    return(E_BADPARM);
}
```

An over-wide line or an under-specified matrix now reports a clean `E_BADPARM`
error naming the shortfall, instead of the out-of-bounds access. A
correctly-specified coupled line (1–8 conductors with full R/L/C/G triangles) is
unaffected — the check passes exactly the inputs the loops require.

## Verification

`examples/cplfix_examples/verify_cplfix.py` (3 checks, both solvers): a valid
2-conductor coupled line still simulates; a 2-conductor line whose R/L/C/G give
only one value each is rejected with a clean "needs 3 entries" error; and a
9-conductor line is rejected with a clean "between 1 and 8" error — both without
crashing. Both out-of-bounds accesses were reproduced (ASan at `cplsetup.c:474`,
UBSan at `cplsetup.c:430`) and shown fixed.

## Scope

Core ngspice, one device (`spicelib/devices/cpl/cplsetup.c`); the ngspice binary
is rebuilt. No solver, analysis, or numerical change; a correctly-specified
coupled line is unaffected. Full regression: all examples pass.
