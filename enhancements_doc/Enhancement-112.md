# Enhancement-112 — KLU support for the globalized-Newton line search

[Enhancement-111](Enhancement-111.md) added `.option linesearch`, a globalized
(damped) Newton whose merit function is the true KCL residual
`‖F‖ = ‖G·x − b‖`, computed mid-solve with ngspice's sparse matrix-vector
product `SMPmultiply`. That merit was only ever exercised under the **Sparse 1.3**
solver. Under the **KLU** solver (`.option klu`), enabling the line search
**crashed ngspice with a segfault**:

```
.option klu
.option linesearch
   → SIGSEGV in klu_matrix_vector_multiply
```

This enhancement fixes that: the line search now runs correctly under **both**
linear solvers.

## Root cause — an unfinished KLU code path

`SMPmultiply` dispatches to a KLU-specific matrix-vector product when KLU is the
active solver (`src/maths/KLU/klusmp.c`):

```c
klu_matrix_vector_multiply(Ap_CSR, Ai_CSR, Ax_CSR, RHS, Solution,
                           NULL, NULL,        /* IntToExtRowMap, IntToExtColMap */
                           N, Common);
```

It passes **`NULL`** for the internal↔external ordering maps. But
`KLU_matrix_vector_multiply` (`src/maths/KLU/klu_multiply.c`) dereferenced them
unconditionally:

```c
pExtOrder = &IntToExtColMap[n];          /* &NULL[n] = n·sizeof(int) */
... Solution[*(pExtOrder--)] ...         /* reads address 0x14 for n=5 → SIGSEGV */
```

`&NULL[5]` is `0x14` — exactly the faulting address. The line search is the
**only** caller of `SMPmultiply` under KLU, so this dead path had never been
exercised before and its NULL-map case was never implemented.

## The fix

Passing `NULL` for the ordering maps is `SMPmultiply`'s way of saying *"the matrix
and the RHS/Solution vectors are already in the same order"* — the KLU CSC arrays
and the circuit vectors share the external node ordering. So a NULL map means the
**identity** ordering. `KLU_matrix_vector_multiply` now treats it as such:

```c
ei = (IntToExtColMap != NULL) ? IntToExtColMap[i + 1] : (i + 1);
```

applied symmetrically to the gather (`Solution`) and scatter (`RHS`) loops, in
both the real and complex builds. The `i + 1` is the one bookkeeping subtlety: the
KLU CSR is 0-based while ngspice's RHS/Solution vectors are 1-based (index 0 is the
grounded reference), so internal index `i` maps to external index `i + 1`.

Normal KLU factor/solve is untouched — `SMPmultiply` is called *only* by the line
search, so nothing else changes.

## Verification

Built against the repository ngspice (KLU enabled) and checked end-to-end:

- **No crash.** `.option klu` + `.option linesearch` now converges the BJT test to
  `v(c) = 2.442076 V` (was SIGSEGV).
- **Numerically correct, not just non-crashing.** The residual merit sequence under
  KLU is **identical to Sparse 1.3** at every iteration —
  `28.15 → 21.20 → 9.75 → 1.54 → 0.032 → 1.3e-5` — matching to ~11 significant
  digits (the last-digit differences are summation-order rounding). A wrong
  matrix-vector product would have produced a different merit.
- **Result-neutral** across the [linesearch battery](../examples/linesearch_examples/)
  (BJT, BJT+diode, two-diode divider, bistable latch): `klu`+linesearch ==
  `sparse`+linesearch == `klu` without linesearch.
- **Backtracking path** (λ<1), forced with a temporary damped-step hook, reaches
  the correct root under KLU at λ = 0.5, 0.25 and 0.1 — matching Sparse.
- **Full example suite**, run under **both** solvers, is `101/101` OK; the
  `linesearch` example is now `17/17` under KLU (it was crashing, `9/17`, before).
- **No regression** to normal KLU operation on non-line-search circuits.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/maths/KLU/klu_multiply.c` | `KLU_matrix_vector_multiply` treats NULL `IntToExt{Row,Col}Map` as the identity ordering (`ext = i + 1`) instead of dereferencing NULL; applies to the gather and scatter loops in both the real and complex builds |

This also corrects the record for Enhancement-111: its line search is now genuinely
verified under both KLU and Sparse 1.3 (the earlier "both solvers" note reflected a
mislabeled test in which both runs were in fact Sparse).
