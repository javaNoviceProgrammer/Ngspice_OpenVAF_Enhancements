# Enhancement-470 — tearing an OSDI circuit down was quadratic

`CKTdltNNum()` finds the node it is asked to delete by scanning the circuit's
node list from the head, and `OSDIunsetup()` calls it once per internal node. So
unsetting a device that owns *k* of them costs O(k·N) in a circuit of N nodes,
and every repeated analysis pays it — a `sweep`, an `optimize`, a `montecarlo`,
anything that runs an analysis more than once.

## The scope note was wrong, and instrumenting is what showed it

This work was scoped as *"move `sweep`'s loop into the analysis kernel the way
`.dc` does"*, on the theory that the ~20 ms/point gap between a sweep point
(~30 ms) and an `op` analysis (9.4 ms) was per-point **setup**. The scope note
put instrumentation first and said, in as many words, *"Do not skip this step —
the whole case rests on it."*

It did. A profile of a 1001-point parameter sweep over a 2448-unknown circuit:

```
10083 com_sweep -> sw_run_cmd -> dosim -> if_run
  8092 CKTdoJob
    8083 CKTunsetup
      8056 OSDIunsetup
        7808 CKTdltNNum          <- 77% of the entire run
```

Not setup. Not the solve. **Teardown** — and a quadratic one. The kernel-loop
rewrite would have been a large, risky change aimed at the wrong 20 ms.

## The fix

`OSDIunsetup()` knows every node number it wants gone before it deletes any of
them. It now marks them and lets **one walk of the list** remove them all:
O(N) for the whole unsetup instead of O(k·N). `CKTdltNodeSet()` in
`spicelib/analysis/cktdltn.c` does the pass; `CKTdltNNum()` is unchanged and
still serves every other caller.

**One subtlety cost a second profile.** The first version sized its mark array
from `ckt->CKTmaxEqNum`, which *shrinks as nodes are deleted*. `OSDIunsetup()`
runs once per model **type**, so the second type's node numbers sat above the
now-smaller bound, failed the range test and fell back to the per-node path.
The speedup was 23% and the profile still showed `CKTdltNNum` at 64%. The bound
is now the highest node number actually present in the list, taken by walking it
once.

## Measured

Per sweep point, on the dielectric stack this came from:

| stack periods | unknowns | before | after | |
|---|---|---|---|---|
| 5 | ~490 | 1.7 ms | 1.2 ms | 1.4× |
| 10 | ~980 | 4.0 ms | 2.3 ms | 1.8× |
| 25 | 2448 | 32.9 ms | 7.6 ms | **4.3×** |

The speedup **growing with circuit size** is the signature of removing a
quadratic. The full 1001-point deck: **29.78 s → 7.12 s**, results byte-identical.

7.6 ms/point is close to the 9.4 ms a single `op` analysis reports, which is the
honest ceiling here: the teardown overhead is essentially gone.

## What dominates now

```
5158 CKTdoJob -> DCop -> CKTop -> NIiter
  3888 spOrderAndFactor          <- 51%
1672 CKTsetup
 718 CKTunsetup
   503 CKTdltNodeSet  (497 of it IFdelUid)
```

Teardown fell from 80% to 9%, and what is left of it is `IFdelUid` unhooking
names from the symbol table, not list scanning. The dominant cost is now
`spOrderAndFactor` — genuine matrix work.

There is a further opportunity there, deliberately **not** taken here: between
sweep points the matrix *structure* does not change, only its values, so the
ordering could be computed once and only the factorisation repeated. That is
exactly what `klu_refactor` does — and Enhancement-439 recorded that it reuses
the old pivot order with **no pivoting and no singularity test**, which produced
a NaN solve on a circuit SPARSE handled. Any such reuse needs that hazard
answered first, so it belongs in its own change with its own evidence.

## Verification

`examples/teardown_examples/verify_teardown.py` — **11/11**, both solvers.

A teardown that frees the wrong node, frees one twice, or leaves one behind
would corrupt the *next* analysis rather than fail loudly, so most of the suite
is about the numbers and the bookkeeping, not the clock:

- a single `op` matches the analytic ladder voltages;
- three `op`s in a row give the identical answer;
- a 5-point sweep gives five distinct values that match `op`s taken by hand at
  the same knob settings;
- two successive analyses expose the same vectors, and the same N internal nodes
  appear each cycle rather than accumulating;
- an internal node holds its analytic value across three setup/teardown cycles;
- five cycles raise no error.

The two timing checks assert **scaling**, not milliseconds — doubling the
instance count must cost well under 4× per point — because an absolute figure
would only measure the machine.

Full regression: see the change report. ngspice-only.
