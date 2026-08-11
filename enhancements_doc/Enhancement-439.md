# Enhancement-439 — a successful `klu_refactor` is not necessarily a usable one

KLU failed an operating point that SPARSE solves. Not more slowly — it produced
NaN, reported success, and then burned 33,911 iterations before giving up with a
message that named neither the node nor the cause.

```
                     SPARSE                    KLU
  v(nb)              0.5                       FAIL
  iterations         289                       33,911
  NaN in output      no                        yes
```

The circuit is the textbook one: the midpoint of two series capacitors, a node
with no DC path.

```
V1 in 0 dc 1
C1 in mid 1u      <- 'mid' has no DC path
C2 mid 0 1u
R1 in nb 1k       <- this divider is perfectly well determined: v(nb) = 0.5
R2 nb 0 1k
```

## What the instrumentation showed

Four hypotheses were tried and discarded before instrumenting; each is recorded
at the end of this document so the dead ends are not re-walked. Probes on
`LoadGmin_CSC`, `klu_factor`, `klu_refactor` and `klu_solve` produced the answer
in one run:

```
[439] LoadGmin: diag[3] is NULL -> Gmin NOT applied to this row
[439] LoadGmin n=4 Gmin=1e-12 rows_without_diagonal=1
[439] klu_refactor ret=1 status=0 rank=-1 singcol=0 gminflag=1
[439] klu_solve   ret=1 status=0 firstNonFiniteRow=1        <- NaN, after a "successful" refactor
```

Two facts, both necessary:

1. **Gmin never reaches the offending row.** `LoadGmin_CSC` walks the diagonal
   pointers and skips any that are NULL — "Not all the elements on the diagonal
   are present, when the circuit is parsed". A node with no DC path has no
   diagonal entry at all, so the one row that needs regularising is the one row
   that cannot receive it. Rows 0–2 get Gmin; row 3 never does.
2. **`klu_refactor` does not detect that the result is unusable.** It reuses the
   pivot ordering chosen by the last full `klu_factor` and only refills values —
   no pivoting, no singularity test. Once gmin stepping ramped down to 1e-12 the
   reused ordering produced zero/NaN pivots, and refactor returned
   `ret=1, status=KLU_OK`.

After that first NaN there were **33,835 further non-finite solves**, with
refactor reporting OK **33,191 times**. NaN neither satisfies a convergence test
nor trips a singularity test, so the Newton loop and every rung of `CKTop`'s
homotopy ladder — dynamic gmin, static gmin, source stepping, pseudo-transient,
optran — each ran to its full iteration budget on a factorization that was
already garbage. The count is invariant at 33,911 for any circuit size, which is
the signature of a fixed iteration budget rather than real work.

SPARSE solves the same circuit because its refactor path *does* detect the zero
pivot and forces a full reorder (`NISHOULDREORDER; continue;`). KLU had no
equivalent.

## The fix

`klu_rcond` is the cheap, exact test: it walks `diag(U)` and sets `rcond = 0`
with `status = KLU_SINGULAR` the moment it finds a zero or NaN pivot. Calling it
after a successful `klu_refactor` and returning `E_SINGULAR` when it reports
singular routes the caller into the reorder-and-factor-again path it already
has — which pivots properly. That is the same recovery SPARSE performs, and it
needed no new plumbing.

The relevant `klu_factor` path already returned `E_SINGULAR` correctly; only the
refactor shortcut was unguarded.

## Cost

`klu_rcond` is O(n) against a refactor's O(nnz), so it is a constant fraction:

| ladder size | factor time before | after | total analysis before | after |
|---|---|---|---|---|
| 500 | 0.01341 s | 0.01454 s (+8.4 %) | 0.105 s | 0.105 s |
| 2000 | 0.05334 s | 0.05939 s (+11.3 %) | 0.418 s | 0.416 s |
| 6000 | 0.16399 s | 0.17766 s (+8.3 %) | 1.489 s | 1.454 s |

About 10 % of the factor step, and **nothing measurable on total analysis time**,
because factoring is roughly a tenth of a transient's work. Iteration counts on
healthy circuits are identical before and after (2032/2032, 2035/2035,
2037/2037), so nothing about ordinary convergence changed.

## What this does not fix

The underlying asymmetry remains: **Gmin still cannot be applied to a row with
no diagonal entry**, because the CSC structure is fixed at symbolic-analysis
time and there is no slot to add it to. The fix makes KLU recover the way SPARSE
does rather than removing the cause. Allocating a diagonal entry for every node
at matrix-build time would address it at the root, at the cost of a slightly
denser pattern for every circuit — a change with its own performance case to
make, and deliberately not bundled here.

## Four hypotheses that were wrong

Recorded because each looked convincing and cost a build:

1. **Short-circuit `CKTop`'s ladder on `E_SINGULAR`**, mirroring Enhancement-378's
   `E_PANIC` guard. **Wrong and dangerous**: the ladder is not wasted — gmin
   stepping legitimately rescues a floating node, and the circuit genuinely
   solves. This guard would have turned working decks into failures. Caught only
   by testing whether any aid rescues the circuit *before* writing code.
2. **`KLUloadDiagGmin = 0` on the refactor-retry path** in `niiter.c` — the
   comment there says "take the same matrix" while the flag makes it a different
   one. Patching it changed nothing: that branch is never reached for this
   circuit ("KLU ReFactor failed" never prints).
3. **Force `NISHOULDREORDER` before `OPtran`.** No change.
4. **Act on `KLUmatrixCommon->status` after `SMPsolve`** in `niiter.c`. No change
   — the status is `KLU_OK` there, because the singular verdict belongs to the
   factorization, and `klu_refactor` never produced one.

The invariant 33,911 was the tell each time: a patched path that does not move
the number is not the live path.

## Verification

* **`examples/klusingular_examples` — 16/16.** The split is pinned closed
  (KLU 0.5 in 287 iterations against SPARSE's 0.5 in 289), no NaN reaches the
  output, and the rescue is checked to survive with gmin stepping off, source
  stepping off, and both off. Because the fix adds a check to *every* refactor,
  the controls matter as much: three healthy circuits are checked to give
  identical answers and identical iteration counts on both solvers, and a
  30-diode transient — which hammers the refactor path — is checked to be
  bit-identical between solvers.
* **op-convergence campaign: 105/105 combinations** (21 circuits × 5 option sets
  × 2 solvers) both solvers converge, **0 splits, 0 answer differences, 0
  analytic mismatches**. Before the fix the same campaign showed 3 splits.
* **Full regression 350/350**, both solvers.

## Found by

The op-convergence robustness campaign, which was run to answer "are SPARSE and
KLU equivalent?". They are — on 102 of 105 combinations they agree not just on
the answer but on the iteration count. The three that disagreed were all this
defect.
