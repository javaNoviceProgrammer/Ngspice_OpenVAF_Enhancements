# Enhancement-233 — KLU glue: finish the null-check reorder + correct the collapse map

A follow-up to [E-232](Enhancement-232.md), from a deeper audit of the same file
(`src/maths/KLU/klusmp.c`). Two more latent defects, both fixed. Both are
behaviour-preserving for every circuit — one path never triggers, the other is
confirmed-dead code — so this is pure correctness hygiene, not a behaviour change.

## What the deeper audit established first

Before fixing anything, two scarier-looking candidates were **investigated and
cleared** by empirical test, not just inspection:

* **A suspected re-analysis memory leak was refuted.** `.pz`/`.sens` reuse
  `ckt->CKTmatrix` and call `SMPconvertCOOtoCSC` + `SMPpreOrder` again, neither
  of which frees the prior arrays/`Symbolic` — which *looks* like a per-analysis
  leak. Instrumenting the lifecycle over `op → pz → sens` showed the opposite:
  every convert/preorder call sees a **fresh** matrix (`Ap == NULL`,
  `Symbolic == NULL`), and `SMPnewMatrix`/`SMPdestroy` are **balanced** (5 new /
  4 destroy / 0 overwrite-without-destroy). ngspice tears down and rebuilds the
  matrix per analysis, so no arrays are ever leaked. No fix was made — there is
  no bug.
* **Node-collapse is dead code.** Instrumenting the collapse branch and sweeping
  the whole 191-example regression (every OSDI model, pz, sens, noise) plus
  pathological topologies: it **fired 0 times**. `osdisetup.c` explains why —
  OSDI collapses nodes at allocation time (a collapsed node gets no matrix
  column), so the COO never has a gap, and Gmin fills every diagonal.

## The two fixes

**Fix 3 — finish E-232's null-check reorder.** E-232 fixed a
dereference-before-`NULL`-check in `SMPluFac` and `SMPsolve`, but the identical
pattern survives in two functions it did not touch: `SMPcReorder` and
`SMPreorder` read `KLUmatrixCommon->status` before the `== NULL` guard. Both are
reordered to check `NULL` first (early `return`, matching `SMPcLUfac`), so the
status fields are read only when `Common` is guaranteed non-NULL. While there,
two mislabeled diagnostics were corrected (the `Common`-NULL and `Symbolic`-NULL
branches each printed a stray "KLUnumeric object is NULL"). As with E-232,
`Common` is never actually NULL here, so behaviour is unchanged — this closes the
static-analyzer finding at the remaining sites.

**Fix 2 — correct the collapse map for the multi-gap case.** In
`SMPconvertCOOtoCSC`, the structural-zero-column compaction records the
new→old node map as `NewToOld[reduced] = MatrixCOO[i].col`. With **two or more**
gaps the right-hand side is a *partially-reduced* index from an earlier pass, not
the true original column, so the map would resolve to the wrong node and the
real `SMPsolve` gather/scatter would mis-address the RHS. Fixed by chaining
through the existing map — `NewToOld[reduced] = NewToOld[MatrixCOO[i].col]` —
which holds the original (identity on the first pass, so single-gap behaviour is
unchanged). This path is confirmed dead (see above), so the fix is defensive: it
makes the code correct *should* it ever become reachable, rather than silently
corrupting a solve.

## Verification

Behaviour-preserving, so no new example: the existing
[`examples/solverfix_examples`](../examples/solverfix_examples/) suite (KLU vs
SPARSE bit-agreement on AC, noise, and pole-zero over an asymmetric network) is
the relevant check, and it — together with the **full 191/191 regression** —
remains unchanged. Fix 2's dead path cannot be exercised by construction; its
correctness is by the chaining argument above.

## Scope

ngspice only, one file (`src/maths/KLU/klusmp.c`); no analysis, device, OSDI, or
compiler change, and no behavioural change for any circuit. Full regression:
191/191.
