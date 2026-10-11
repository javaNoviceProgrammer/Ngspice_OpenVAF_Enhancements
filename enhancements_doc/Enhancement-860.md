# Enhancement-860: the ac solve refines its answer — threshold pivoting cost up to 6 digits on inductive networks at low frequency

**Scope:** F5 of the
[third robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

ngspice:
- `maths/ni/niaciter.c`: `ac_refine` after the solve in `NIacIter` and in the S-parameter
  path's `NIspSolve`.
- `maths/KLU/klusmp.c` and `maths/sparse/spsmp.c`: `SMPcCopyLoaded` (Sparse's loaded values
  before the factorization) and `SMPcResidual`, declared in `include/ngspice/smpdefs.h`.

`examples/acrefine_examples/` (new). **ngspice only.**

**Suites:**
- [`acrefine_examples`](../examples/acrefine_examples/): 4 of 4 per solver. On the E-859
  binaries 3 fail under Sparse and 2 under KLU; [4] is a control.
- The campaign's Family A, both runs, against the exact complex MNA solve:
  - 300 inductor-heavy networks from 0.1–10 Hz up: 22 flagged under Sparse and 5 under KLU,
    and 5 where the solvers disagreed; now 1 under each and none. The one left is off by 1.5e-9
    under both solvers alike, as it was before, so it is not the solve.
  - The 300 ordinary networks: 4 flagged; now none.
- The full sweep: 566 of 566.

## What was wrong

The ac matrix is factored with threshold pivoting: a pivot is accepted down to `pivrel` (1e-3) of
its column's largest entry. Sparse orders the matrix once, at the first frequency, and reuses
that order. At a few hertz a 1 nH inductor's branch row carries jωL ~ 1e-8 beside entries of
order 1. On 300 such networks:

| | networks over 1e-9 × cond | worst error | worst condition |
|---|---|---|---|
| Sparse | 22 | 3.4e-6 | 5 |
| KLU | 5 | 2.0e-7 | 5 |

On matrices of condition 5, any backward-stable solve gives 1e-15; `pivrel=1` gave 2e-16. In the
first run's ordinary networks, 4 of 300 lost digits the same way.

## The change

One step of iterative refinement after each ac solve, two at most:
1. Before the factorization, the loaded matrix A is kept. Sparse factors in place, so
   `SMPcCopyLoaded` copies its values. The element list is built once per matrix; an element
   keeps its external row and column through a reordering, and a fill-in holds 0 when loaded.
   KLU factors into its own object and keeps A as it is, so nothing is copied.
2. After the solve, `SMPcResidual` gives r = b − Ax and |A||x| + |b|, row by row. The
   componentwise backward error is max |rᵢ| / (|A||x| + |b|)ᵢ.
3. Where that is above 64 ε, A d = r is solved with the same factors, and x + d is kept if its
   backward error is smaller.

A row whose terms are below DBL_MIN/ε, such as the far end of a deep stopband at 1e-300, has no
measurable backward error and is left out of the measure. A point that was solved well is left
exactly as it was: same factors, same pivots, same bits. `pivrel` keeps its meaning.

**The cost** is one pass over the matrix per frequency, plus the Sparse copy, and one more
back-substitution where the measure says so. Measured at 9 000 points, best of five runs:

| circuit | Sparse | KLU |
|---|---|---|
| RLC ladder, 2 400 unknowns | +20 % | +9 % |
| 150 BJT stages | +25 % | +12 % |
| 200 BSIM4 stages | +10 % | +6 % |

These are circuits whose devices load almost nothing. Where devices load real models the load
dominates and the share is smaller. None of the three needed a refinement step at any point.

## The checks

`acrefine_examples`: the campaign's worst networks, swept as the campaign swept them, against
the exact complex solve at each of ngspice's frequencies.
- **[1]** Network 5025 (3.4e-6 under Sparse on E-859) to 1e-12. It comes out 3e-16.
- **[2]** Networks 5043, 5210 and 5049 to 1e-12.
- **[3]** Network 5035 (4.9e-8 under KLU on E-859) to 1e-12.
- **[4]** (control) A well-conditioned RLC ladder to 1e-13.
