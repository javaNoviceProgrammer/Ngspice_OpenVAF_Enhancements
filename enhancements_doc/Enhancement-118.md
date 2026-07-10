# Enhancement-118 — PSS runs under the KLU solver

[Enhancement-117](Enhancement-117.md) shipped periodic steady state (`.pss`) but
had to **guard it to the Sparse solver**: under `.option klu` the shooting loop
*hung* — it stalled and spun indefinitely, even though a plain `.tran` on the same
circuit runs fine under KLU. This enhancement finds and fixes the cause, so PSS
runs correctly under **both** linear solvers, and removes the guard.

## Diagnosis

It was never a crash or a wrong answer — it was a **timestep explosion**. By
instrumenting the PSS transient loop and comparing the per-step `delta` (timestep)
trajectory of the two solvers on the same RC deck:

- Both start **identically** (stabilization delta doubling `2e-10 → 4e-10 → 8e-10 → …`).
- At step 5 they diverge: Sparse keeps doubling cleanly (up to `4e-7`), but KLU's
  `CKTtrunc` (local truncation error) returns a *slightly smaller* step and never
  fully recovers — the timestep collapses to `~1e-13` and stays there.
- Result: KLU takes **~21 million** timesteps to Sparse's ~9.6 million — so a
  `.pss` that finishes in ~2 minutes under Sparse never finishes under KLU.

The root cause is the linear-solver **re-factorization**. `NIiter` normally reuses
`klu_refactor` — which keeps the pivot ordering from the last full factorization
and only recomputes the numerical values — for speed. Across PSS's extremely fine,
breakpoint-dense shooting timesteps, that reused ordering accumulates just enough
numerical error to inflate the truncation error, which shrinks every subsequent
step. Sparse's own factorization is accurate enough not to trigger this, and a
plain `.tran` under KLU is unaffected because its steps are coarse enough that the
tiny refactor error never matters.

## The fix

In [`dcpss.c`](../ngspice-46/src/spicelib/analysis/dcpss.c), under KLU, force a
full re-factorization every PSS timestep by setting `NISHOULDREORDER` before the
Newton iteration:

```c
/* Enhancement-118: under KLU, force a full factorization every PSS timestep. */
if (ckt->CKTmatrix->CKTkluMODE)
    ckt->CKTniState |= NISHOULDREORDER;
converged = NIiter(ckt, ckt->CKTtranMaxIter);
```

`NISHOULDREORDER` makes `NIiter` take the accurate `SMPreorder` (`klu_factor`,
re-pivoted) path instead of `klu_refactor`, so the truncation error — and hence
the timestep — matches Sparse. The E-117 KLU refusal guard is removed. The change
is gated on `CKTkluMODE`, so the Sparse path and plain `.tran` are untouched.

## Verification

The 1 MHz-driven RC low-pass (`R=1k`, `C=1n`) under both solvers:

| Solver | Converges | Fundamental frequency | Fundamental magnitude | Time |
|---|---|---|---|---|
| Sparse (unchanged) | iter 22 | 999999.8976 Hz | 0.1571762 | ~2 min |
| **KLU** (was hanging) | iter 22 | 999999.8976 Hz | **0.1571762** | ~3.7 min |

KLU now converges to the **identical** result as Sparse (analytic `|H(1MHz)| =
0.157136`). It is ~1.8× slower (a full factor every step vs. a refactor), which is
an acceptable cost for a specialized analysis that previously did not complete at
all. `examples/rfpss_examples/verify_rcpss.py` now runs the deck under **both**
solvers and asserts they agree.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/dcpss.c` | force a full KLU re-factorization each PSS timestep (`NISHOULDREORDER`); remove the E-117 Sparse-only guard |
| `examples/rfpss_examples/verify_rcpss.py` | run the PSS deck under both Sparse and KLU and assert the converged frequency and fundamental agree |

## Scope

PSS now runs under both Sparse 1.3 and KLU, closing the last KLU gap opened by
E-117. It remains a brute-force shooting method and the foundation for the RF
periodic small-signal suite (PAC / pnoise / PXF, future work).
