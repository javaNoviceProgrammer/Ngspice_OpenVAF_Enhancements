# CPL coupled-line out-of-bounds accesses (Enhancement-248)

Two out-of-bounds accesses in the **CPL** coupled multiconductor transmission
line (`p` device, model type `cpl`) — a **core** ngspice device — found by
fuzzing the conductor count and the R/L/C/G matrix sizes, confirmed with
AddressSanitizer / UndefinedBehaviorSanitizer.

A CPL line has `noL` conductors. `noL` (the instance's `dimension`) comes from
the node count on the `p` card, and each of the symmetric R/L/C/G matrices is
supplied as its upper triangle — `noL*(noL+1)/2` values. `CPLsetup` / `ReadCpL`
(`spicelib/devices/cpl/cplsetup.c`) validated neither count.

**1. Under-specified matrix — heap OOB read.** `ReadCpL` fills the matrices with

```c
f = CPLmodPtr(here)->Rm[counter];   /* and Lm/Cm/Gm[counter] */
```

where `counter` runs `0 .. noL*(noL+1)/2 - 1`, but `Rm`/`Lm`/`Cm`/`Gm` are
allocated to the number of values the user actually gave. Fewer values than the
triangle needs → read past the end:

```
ERROR: AddressSanitizer: heap-buffer-overflow ... READ of size 8
    #0 ... in ReadCpL cplsetup.c:474
```

**2. Too many conductors — fixed-array overflow.** `ReadCpL` uses
`RLINE *lines[MAX_CP_TX_LINES]` and `CPLine.in_node[MAX_CP_TX_LINES]` with
`MAX_CP_TX_LINES == 8`, indexed by `noL`. A `p` card with more than 8 conductors
writes past those arrays:

```
UndefinedBehaviorSanitizer: index 8 out of bounds for type 'NODE *[8]'
    cplsetup.c:430
```

Both are reachable from a valid-syntax netlist (a `p` line with too few matrix
entries, or with more than 8 conductors). On the release binary the reads pull
adjacent heap — heap-layout-dependent garbage that here trips a downstream "fatal
error" but could equally produce wrong results or crash.

**Fix.** Validate both up front in `CPLsetup`, right after `noL = here->dimension`:
reject `noL < 1 || noL > MAX_CP_TX_LINES`, and reject any R/L/C/G matrix with
fewer than `noL*(noL+1)/2` entries — a clean `E_BADPARM` error naming the
shortfall, instead of the out-of-bounds access.

`verify_cplfix.py` (3 checks, both solvers): a valid 2-conductor coupled line
still simulates; a 2-conductor line whose R/L/C/G give only 1 value each is
rejected with a clean "needs 3 entries" error; and a 9-conductor line is rejected
with a clean "between 1 and 8" error — both without crashing.

```
python3 verify_cplfix.py
```

## Scope

Core ngspice, one device (`spicelib/devices/cpl/cplsetup.c`); the ngspice binary
is rebuilt. No solver, analysis, or numerical change; a correctly-specified
coupled line (1–8 conductors with full R/L/C/G triangles) is unaffected.
