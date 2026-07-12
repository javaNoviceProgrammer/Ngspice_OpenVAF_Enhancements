# Enhancement-173 — Eigenvalue-based pole-zero (`.options pzeig`)

[E-171](Enhancement-171.md)/[E-172](Enhancement-172.md) fixed the KLU-side
defects in pole-zero analysis, but the root finder itself — a ~1990 **Muller
iteration on determinant values** — remains fragile in both solvers: iteration
limits ("giving up after 231 trials" on a plain RLC bandpass), noise-floor
stalls, and chaotic search-path sensitivity. This enhancement adds a modern
alternative: **`.options pzeig`** computes every pole and zero at once as a
dense eigenvalue problem. The default remains Muller; the new method is opt-in.

![pzeig](../examples/pzeig_examples/pzeig.png)

## The method

The existing `CKTpzSetup`/`CKTpzLoad` machinery already builds the right
matrix for both phases — poles and zeros are the roots of `det(A(s)) = 0` for
the respective PZ-configured `A(s)`, which is **affine in s**: `A(s) = G + sC`.

1. **Extract the pencil densely.** Load at `s=0` and `s=1`; a new
   solver-agnostic `SMPdenseExtractReal` (KLU: walk the CSC arrays; Sparse:
   walk the column lists through the Int→Ext translation maps) gives
   `G = A(0)` and `C = A(1) − A(0)`. A third load at an arbitrary point
   verifies affinity, so any hypothetical non-polynomial device falls back
   with a clear message instead of wrong roots.
2. **Shift-invert linearization.** `C` is structurally singular (rows/columns
   with no dynamic elements), so the pencil is not inverted directly: factor
   `(G + σC)` **once** at a non-root shift σ (tried from a small ladder of
   shifts, using the circuit's own sparse solver — Sparse or KLU), then form
   the dense `M = (G + σC)⁻¹C` with n sparse solves. From
   `(G + sC)v = 0 ⇔ Mv = μv` with `μ = 1/(σ − s)`: every finite root is
   `s = σ − 1/μ`, and the pencil's **infinite eigenvalues land harmlessly at
   μ = 0** (dropped by a noise-floor threshold).
3. **Dense QR.** The eigenvalues of the real matrix M come from a new
   self-contained eigensolver, `maths/dense/eig.c` — the classical
   **balance / Hessenberg / Francis double-shift QR** chain (the EISPACK
   `balanc`/`elmhes`/`hqr` lineage, written fresh; no LAPACK dependency) —
   unit-tested standalone against companion matrices, complex pairs, a 50×50
   tridiagonal with known spectrum, and a badly-scaled balance case.

The roots go into the same `PZtrial` list the Muller driver produces, so
`PZpost` output, `print all`, and every downstream consumer are unchanged.

## What it fixes in practice

| Case | Muller | `pzeig` |
|---|---|---|
| RLC bandpass (Sparse) | iteration-limit warning, correct roots after 231 trials | same roots, **no warning, no iteration** |
| twin-T notch | 6/6 under Sparse, historically stalled under KLU (pre-E-172) | **6/6 under both solvers**, notch zeros ±j·10⁶ |
| 10-section RC ladder | 10/10 (many trials) | **10/10 matching the analytic tridiagonal formula** `s_k = −(2−2cos((2k−1)π/21))/RC` |
| bandstop imaginary zeros | exact | **exact** (0 ± j·10⁶ to the printed digit) |
| balanced/differential output | works (E-172) | works |

## Plumbing

`.options pzeig` flows like every task option: `OPT_PZEIG` (optdefs.h) →
`cktsopt.c` IFparm entry + setter → `TSKpzEig` (tskdefs.h) → copied to
`CKTpzEig` flag in `cktdojob.c` → dispatch in `pzan.c` (both the poles and
zeros phases call `CKTpzEig()` instead of `CKTpzFindZeros()`). New files:
`spicelib/analysis/cktpzeig.c` (the method) and `maths/dense/eig.c` (the
eigensolver); `SMPdenseExtractReal` added to the KLU↔SMP bridge.

## Verification

[`examples/pzeig_examples/verify_pzeig.py`](../examples/pzeig_examples/verify_pzeig.py)
— 13 checks driving both solvers and both methods: the RLC conjugate pair, the
10-pole ladder against the analytic formula *and* against Muller root-for-root,
the bandpass warning-free equivalence, the twin-T 6-root set, the bandstop's
exact imaginary zeros, balanced output, the purely resistive no-roots edge
case, and that the **default method remains Muller**. Full example regression:
136/136.

## Scope

Dense O(n²) memory / O(n³) QR, capped at 2000 unknowns (ample for the
small-signal blocks PZ is used on; above the cap it errors with a pointer back
to Muller). Root accuracy is dense-QR class — absolute error ~machine-eps ×
dominant-root magnitude — so an exact origin-zero can print as ~1e-7 when poles
sit at 10⁶ rad/s; Muller refines locally and can resolve wider per-root dynamic
range, while `pzeig` never misses or invents a root. The two methods agree to
≥6 digits on every circuit in the battery.
