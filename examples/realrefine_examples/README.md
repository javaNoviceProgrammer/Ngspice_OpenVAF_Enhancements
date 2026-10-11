# realrefine_examples — Enhancement-867

[E-867](../../enhancements_doc/Enhancement-867.md): F1 and F2 of the
[Sparse and KLU correctness campaign of 2026-10-11](../../docs/bug_hunts/2026-10-11_sparse-klu-correctness-campaign.md).

Under Sparse, a follower built from a VCVS of gain A, whose feedback runs through a 0 V source,
lost about A times the rounding of a double. At a gain of 1e12 the operating point was 1.8e-5
high after 126 iterations of gmin stepping and a transient 2.4e-4 off; at 1e15 the transient was
25 % off. A dc sweep of a resistance kept the pivot order of its first point, and an ammeter
beside the swept load read up to 0.5 % wrong. KLU was exact on both.

The real solve (op, dc, transient) now refines its answer as the ac solve does since E-860.
After each solve the residual gives the backward error. Where that is above rounding, A d = r is
solved with the same factors, and x + d is kept while it improves.

The checks:
- **[1]** F1: the follower's operating point at gains 1e6, 1e9, 1e12 and 1e15, to 1e-14.
- **[2]** F1: a transient at gains 1e9, 1e12 and 1e15, to 1e-14.
- **[3]** F1 at a gain of 1e12 converges in plain Newton, in at most 5 iterations.
- **[4]** F2: the ammeter, its load swept from 0.1 Ω to 40 MΩ, reads 0.6217/R to 1e-8.
- **[5]** F2 started at 100 Ω: to 1e-8.
- **[6]** A dc sweep of `@e1[gain]` from 1e9 down to 1: to 1e-14.
- **[7]** F3's deck: teraohm dead ends beside a VCVS read v(1) to 1e-12.
- **[8]** (control) Two current sources in a cutset need gmin stepping, whose last solve carries
  `gshunt=1e-6` on both nodes; v(1) is −1e-6 / (g + g/(1 + gR)) to 1e-12, so the shunt stays in
  the refined solve.
- **[9]** (control) The follower wired straight back, and an inverting amplifier, at a gain of
  1e12: exact, as before.

Run: `python3 verify_realrefine.py` (9 checks per solver). On the E-866 binaries [1] to [7] fail
under Sparse; under KLU all pass.
