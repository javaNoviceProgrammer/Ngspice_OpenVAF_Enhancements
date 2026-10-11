# Enhancement-868: the refinement measures every row that carries more than rounding — a 6e-8 A current beside 4e5 A was 1.5e-3 off under Sparse

**Scope:** F3 of the
[Sparse and KLU correctness campaign of 2026-10-11](../docs/bug_hunts/2026-10-11_sparse-klu-correctness-campaign.md).

ngspice: `maths/ni/niiter.c`:
- `ni_residual`: which rows count, against `NI_NOISE_ROW`.
- `ni_refine`: how a step is weighed.
- `ni_kind_scale`, split out of `ni_residual`.

`examples/realrefine_examples/` (checks [10] and [11]). **ngspice only.**

**Suites:**
- [`realrefine_examples`](../examples/realrefine_examples/): 11 of 11 per solver. On the E-867
  binaries [10] fails under both solvers (1.5e-3 under Sparse, 1e-7 under KLU).
- The campaign's families, run again:
  - **C, high gains.** Sparse is wrong in 4 networks, all of condition 7e16 or more. KLU is
    wrong in 3 of the same 4. No network needs more than 20 iterations under either solver;
    after E-867, 3 did under Sparse and 2 under KLU.
  - **A, B.** No network differs between a sweep point and a fresh `op`, or across the scales,
    beyond rounding.
- The full sweep: see [Enhancement-869](Enhancement-869.md), folded with it.

## What was wrong

[Enhancement-867](Enhancement-867.md) measured each row of the residual against the larger of
its own terms, (|A||x| + |b|)ᵢ, and (|A|s)ᵢ, where sⱼ is the largest unknown of j's kind. That
second term was there to keep out a row whose unknowns are all at rounding. Two nodes that a 0 V
source ties to ground are such a row; it reads a backward error of 1 and stopped every step.

But a branch current's scale is the largest current anywhere in the circuit. In the campaign's
seed 187, a 0 V sensor carries 6.17e-8 A while an inductor carries 4.2e5 A. The sensor's KCL
row has a componentwise backward error of 1.3e-4. Against 4e5 A it read 2.3e-16, so it was never
refined, and the sensor stayed 1.5e-3 off under Sparse (KLU 1e-7).

## The change

1. **Which rows count.** A row counts unless its own terms are below 1024 ε of its scale,
   (|A||x| + |b|)ᵢ ≤ 1024 ε (|A|s)ᵢ. Such a row is rounding and nothing else. Every other row is
   measured componentwise, |rᵢ| / (|A||x| + |b|)ᵢ. Seed 187's row, at 1.2e-6 of terms against
   1.5e-7, counts.
2. **How a step is weighed.** A row whose true value is 0 can still count when the solve is poor.
   Its terms are then all error, and they shrink with its residual, so its own ratio stays at 1
   however much better a step makes it. In a numerically singular network one such row went
   from 3.6e-5 to 6.3e-9 and the step was refused. The candidate x + d is now weighed against x
   row by row, over the larger of the two rows' terms.

Seed 187's sensor is now within 1.3e-15 under Sparse and 1.1e-15 under KLU. Seed 365's
1.4e-11 A sensor beside 70 A stays within 2.4e-16, as it was after E-867. The teraohm deck and
F1's follower are unchanged. The ring oscillator, the 20 000-node ladder and the mesh keep their
iteration counts, and their times are within noise of E-867's.

## The checks

`realrefine_examples`:
- **[10]** F3, seed 187: a 6e-8 A sensor beside a 4e5 A inductor current, to 1e-10 of the exact
  value.
- **[11]** F3, seed 365: a 1.4e-11 A sensor beside 70 A, to 1e-10.
