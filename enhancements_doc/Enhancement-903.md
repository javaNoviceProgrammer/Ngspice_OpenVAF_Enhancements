# Enhancement-903: a harmonic-balance spectrum stays the spectrum of a real signal — its residual drifted at 1e-10 A, the absolute tolerance, and the source stepping stalled there

**Scope:** F8 of the
[analyses correctness campaign of 2026-10-16](../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md),
with [E-902](Enhancement-902.md).

ngspice:
- `spicelib/analysis/dcpss.c`: `hb_conj_symmetrize`, called after every Newton update in
  `HBanalyze` (`hb`), `QPSShb` (`qpss … hb`) and `HBOSCanalyze` (`hbosc`).

**ngspice only.**

**Suites:**
- [`hbnewton_examples`](../examples/hbnewton_examples/), new: checks [4] and [5].
- The suites of E-902 pass; the full sweep: 595 of 595.

## What was wrong

The Newton unknowns are 2K+1 complex harmonics per node, V₋K … V_K, each free of the others. A
real signal has V₋ₖ = conj(Vₖ) and a real V₀. The devices see only the real part of the
synthesis, v(t) = Re Σ Vₖ e^{jkωt}, so any part of V with V₋ₖ = −conj(Vₖ) is invisible to
them. The reactive current is formed as a matrix product, (J − J_g)·V, and that does see it. A
Newton step then maps this part through J⁻¹·J_g instead of removing it.

Rounding seeds it, and nothing takes it out. In a stage carrying milliamps it drifted between
1e-11 and 1e-10 A. Run past `tol` on seed 111 of the campaign's Family B, |F| wandered from
5.6e-11 down to 4.7e-11 and back up to 7.3e-11 over 20 iterations. `tol` is an absolute 1e-10, so
a level whose residual floor sat above it never converged:
- Every E-901 failure in Family B stopped at |F| between 1.0e-10 and 1.4e-10.
- With E-902's exact Jacobian alone, seed 105 at K = 48 and seed 111 at K = 16 still stopped
  at 2.1e-10 and 1.3e-10.
- The published spectrum showed it too: the dc harmonic of seed 207's collector carried 5.0e-9 V
  of imaginary part.

## The change

After every Newton update, V is projected onto the spectrum of a real signal:
- each pair is replaced by its conjugate-symmetric mean, Vₖ ← (Vₖ + conj(V₋ₖ))/2 and
  V₋ₖ ← conj(Vₖ);
- V₀ becomes real.

The harmonic h's mirror is Nh−1−h in both the one-tone (k+K) and the two-tone
((k₁+K₁)(2K₂+1) + k₂+K₂) orderings, so one function serves `hb`, `qpss … hb` and `hbosc`.

Run past `tol` the same way, seed 111's residual now sits at 7e-16 to 9e-16, the rounding.

## The checks

`hbnewton_examples`:
- **[4]** Seed 105 at K = 48 converges. E-901: stalled at |F| = 1.05e-10; with E-902 alone, at
  2.1e-10.
- **[5]** Every node's dc harmonic is real, exactly. E-901: no spectrum (the runs stall).

Family B, with E-902: 240 of 240 runs converge (E-901: 232).
