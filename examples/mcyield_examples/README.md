# mcyield_examples — Enhancement-609

`montecarlo ... -track "..." -spec <metric>` accepted the flags together, but a
`-spec` was evaluated on the analysis plot before the tracks ran, so nothing in
it could reach a track's result — the yield of a tracked quantity needed a
hand-written loop. Now the tracks run first and each sample's track plot is kept
until the specs and exprs have read it: `track<k>.<vector>` in a metric names the
k-th `-track` of the command, for the sample being judged (`track1.value`,
`track2.x_out`, `track1.value[0]`, and `track1.hits`, the hit count — 0 on a
miss). A spec on a track that had no hit is a violation, counted apart; an
`-expr` on one leaves nan for that sample. And an `-expr` that does not read a
track is evaluated before the tracks and defined as a vector of the sample's
plot, so `-expr q=... -track "q -spec globalmax -output pk" -spec track1.pk`
chains.

Run: `python3 verify_mcyield.py` (14 checks per solver, both solvers).
