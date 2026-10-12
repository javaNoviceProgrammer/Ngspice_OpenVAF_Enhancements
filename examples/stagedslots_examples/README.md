# stagedslots_examples — Enhancement-874

[E-874](../../enhancements_doc/Enhancement-874.md): F2 of the
[transient stress campaign of 2026-10-12](../../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

A `trbdf2` or `sdirk` step rotates the state history once per stage and splices its interior
stages back out. They were parked in `CKTstates[maxord+1]` (and `CKTstates[maxord]` for `sdirk`),
which the truncation estimate reads as the oldest accepted point at the default `maxord`. The
estimate then scaled as a first-order method's: a sine into an RC took 580 045 points under
`trbdf2` and 265 117 under `sdirk` at `reltol=1e-6`, where trap took 512. The stages now sit above
the history, and `maxord` is pinned to the method's order, 2 or 3.

The checks, on a sine into an RC at `reltol` 1e-3 to 1e-6:
- **[1]** `trbdf2`: the points grow by less than 3 times per decade, and end below trap's.
- **[2]** `sdirk`: less than 2.5 times per decade, and below trap's.
- **[3]** (control) Both are within 1.5 times trap's error against the exact solution at every
  `reltol`.
- **[4]** `maxord` has no effect: `trbdf2` at `maxord=6`, and `sdirk` at 2 and 6, run point for
  point as at the default, and a note says so for 6.
- **[5]** (control) Trap, then `sdirk`, then `trbdf2` in one session, set by `option`, match fresh
  runs.

Run: `python3 verify_stagedslots.py` (5 checks per solver). On the E-872 binaries [1], [2] and [4]
fail under both solvers.
