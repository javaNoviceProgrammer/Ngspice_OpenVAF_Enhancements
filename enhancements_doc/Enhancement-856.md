# Enhancement-856: the pole-zero search divides out its roots analytically — at a complex trial a found root was divided out by its squared distance, and the search lost complex roots on 4 of 252 networks

**Scope:** F1 of the
[third robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

ngspice:
- `spicelib/analysis/cktpzstr.c`:
  - `root_factor`, the factor a found root contributes to the deflation;
  - the test of a repeated complex point;
  - `pz_deflated`, `pz_row_scales`, `pz_c_dominates` and `pz_is_zero`, which decide whether
    a point the search stops at is a zero.
- `maths/KLU/klusmp.c` and `maths/sparse/spsmp.c`: `SMProwMaxReal`, the largest entry of each
  row, declared in `include/ngspice/smpdefs.h`.

`examples/pzdeflate_examples/` (new). **ngspice only.**

**Suites:**
- [`pzdeflate_examples`](../examples/pzdeflate_examples/): 9 of 9 per solver. On the E-855
  binaries 6 fail under Sparse and 7 under KLU; [8] and [9] are controls.
- The campaign's Family C, the 252 pz networks: every pole and zero matches the exact
  generalized eigenvalues under both solvers, against 4 networks with a wrong set on E-855.
- 859 more networks from the same generator, both solvers, 1 718 runs: 20 wrong sets on E-855
  (4 without a warning), 2 now. Those 2 are one network, flagged before too, with a zero at
  1.7e-6 among roots of 1e5 to 1e9, which the search reports as 0. That is zero to rounding;
  only the harness tolerance flags it. Iteration-limit warnings went from 32 to 11, and none of
  the 11 now has a wrong set.
- The existing pz suites (klupz, pzeig, pzhb, pzklu, urcpz, analyses, solverfix) pass.
- The full sweep: 562 of 562.

## What was wrong

The search finds the roots of det(G + sC) one at a time. It divides each root out of the
function it searches for the next. For a found root p and a trial s, the factor was |p − s|²
whenever p − s was complex:
- **A real trial and a complex pair:** that is (s − p)(s − p̄), the pair's factor.
- **A complex trial:** it isn't analytic. A real root was divided out by its squared distance,
  where (s − p) belongs, and a pair by |s − p|², where (s − p)(s − p̄) belongs.

Muller's method fits a quadratic to the function at three points. On this function it had
nothing to converge to. On network 1233 it started next to the pair −1.48e7 ± j5.40e6 and
wandered for 200 trials between −1.6e7 and −1.77e7 with small imaginary parts. The search then
stopped at its iteration limit and reported the roots it had: one pole of four. The values the
search worked with were −det(G + sC)/|s − r₁|² to every digit.

A second defect kept pairs on the jω axis from ever being declared. A complex Muller search ends
when a trial repeats an earlier one. The test asked for equal imaginary parts, and a real part
within 1e-12 of |Re s|. For a pair at ±j1.47e8 the real part was 0, jittering by 1e-9 (1e-17 of
|s|) at the rounding floor, so the test could never be met. Under KLU the search found the pair
to the last digit and still ran to the iteration limit with none of it. Under Sparse it
happened to land on exact sign flips.

Each such run printed "Pole-zero iteration limit reached; giving up after N trials with K roots
found". The campaign's page called the runs silent, which was not so. Still, the plot held a
partial set, and the roots it reported missed ngspice's own ac response by 240 % to 450 %. On
859 further networks, under each solver, 18 runs had a wrong set beyond rounding, 2 of them with
no warning at all.

## The change

**The deflation.** `root_factor` gives a found root's factor: (p − s), or (p − s)(p̄ − s) for a
complex pair, which is stored once. On the real axis, where the search starts, this is bitwise
what it was. At a complex trial the deflated function is now analytic, and Muller converges.

**The repeated complex point.** Two complex points are the same point when they agree to 1e-12
of their modulus, or to 1e-6 for a found root, the real axis's tolerances. A complex point that
repeats is where Muller has converged. `alter()` moves a point along the real axis and isn't
used for it. On the real axis the old test stands.

**Noise is not a root.** Once Muller converges, the search can also stop on the determinant's
rounding noise beyond its last root. At |s| ~ 1e21, s·C has swamped G in some rows. There
Muller stalled on noise, the matrix was now and then exactly singular, and a real bracket closed
on noise's sign changes. Before, the broken Muller wandered there to the iteration limit, so the
answer was right and the warning false. Now such a point is accepted as a root only if the
function grows around it as at a zero: 1e-6 of |s| away it must be at least 2⁷ larger than 1e-9
away, on both sides. At a simple zero the ratio is about 2¹⁰; on noise it is about 1. A point
that fails is an aberration, and the search gives up on it with the existing warning.

**Where the test applies.** Noise of this kind needs s·C to dominate G in a row. So the test
applies only where some row has |s|·max|Cᵢⱼ| ≥ max|Gᵢⱼ| > 0. The row scales come once per
search, from loads at s = 0 and at s = 1e40, through `SMProwMaxReal`. Below that, the search's
zeros are accepted as before. That matters for a zero at s ≈ 0, where G + sC rounds to G and
the matrix is singular whatever the small step.

A determinant that is zero everywhere (the shorted input, every trial a root) is left to the
existing E_SHORT path. `.option pzeig` ([Enhancement-173](Enhancement-173.md)) is unchanged.

## The checks

`pzdeflate_examples`, on networks of the campaign's generator with their exact roots:
- **[1]** Two cancelling pairs: the 4 poles and 4 zeros (1 pole on E-855).
- **[2]** A complex pair of zeros among 5.
- **[3]** A pair of zeros on the jω axis and a far real one (1 of 4).
- **[4]** A jω pair that converged and was never declared (none under KLU on E-855).
- **[5]** Two more networks, poles and zeros.
- **[6]** None of these warns that the search gave up.
- **[7]** The rational function of [1]'s roots is ngspice's own ac response: to 1e-13 under
  Sparse and 5e-13 under KLU (the check asks 1e-9). On E-855 it was off by a factor of 6e6.
- **[8]** (control) A search that goes on past its last root takes no roots from the noise
  at |s| ~ 1e21.
- **[9]** (control) A zero at s ≈ 0 is still a zero.
