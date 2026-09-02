# Enhancement-537: the second hunt round — what the statistical commands were not saying

**Scope:** a second one-hour adversarial hunt over the shipped E-535/E-536
work produced sixteen findings, fourteen reproduced with decks. This
enhancement resolves all sixteen. Two came from E-536 itself and are fixed
as the regressions they were; one is a **critical mis-estimate I introduced
in E-536** that this release turns into an honest refusal; and the largest
group is a single systemic class — five commands that read results back
without ever asking whether the analysis solved.

**Suites:** [`examples/mcpolicy_examples/`](../examples/mcpolicy_examples/)
grows from 18 to **28 checks** (both solvers), the new ten each a hunt
finding with its own repro. Full sweep ALL OK. **No openvaf-r change.**

## The one that matters most: a weighted estimate that quietly collapsed

E-536 taught `highsigma -scale` to weight the OSDI draws it inflates, which
was right in one dimension and dangerous in many. The importance weight is a
**product over every inflated statistical parameter in the circuit** — every
`(* std *)` parameter of every device, including ones the metric cannot
possibly depend on — so its variance grows exponentially with their number.
Measured, with bystander devices on a *disconnected* subcircuit (identical
`failures observed` in every run, proving the physics untouched) against a
true P(fail) of **0.2967**:

| bystander devices | 0 | 2 | 5 | 10 | 20 |
|---|---|---|---|---|---|
| reported P(fail) | 0.282 ✓ | 0.072 | 0.018 | 0.0015 | **2.5e-11** |

Ten orders of magnitude, printed with the same confidence as a good answer.
What E-536 traded was a *bounded* bias (0.42 against a true 0.354) for an
*unbounded* variance — better in one dimension, far worse in the decks people
actually have, where per-instance mismatch supplies dimensions automatically.

The estimator is not fixable by arithmetic: unbiased-but-useless is what
importance sampling does in high dimension. So the command now measures its
own reliability and says when it has none. It computes the **effective sample
size** `ESS = (Σw)² / Σw²` and, when that is under a tenth of the run, states
that the weights have collapsed, gives the number (measured **1.2 out of
400**), explains the cause, and says the P(fail) above is not trustworthy.
The same guard covers the pre-existing netlist `.param` SSS path, which
degenerates identically (20 extra Gaussians took a estimate to 2.4e-04) —
that weakness predates E-536; what E-536 changed was how easily an ordinary
deck reaches it.

Two smaller honesty repairs in the same summary. A weighted mean is **not
automatically a probability** — it printed `1.0445` for a case where all 200
samples failed and the true answer is exactly 1 — so it is now clamped into
`[0,1]` and says when clamping happened. And the "equivalent sigma" guard
used to substitute `0.000` at the boundary, which *reads as P = 0.5*, the
opposite of certain failure; it now reports `n/a` and why.

## Five commands were reading another run's numbers

ngspice leaves the previous run's plot in place when an analysis fails.
E-438/E-445 established the guard for that (`sw_run_failed()`), and it was
applied in `sweep` and `optimize` and **missing entirely** in `highsigma`,
`wcd`, `aging`, `emir` and `loadpull`. Each now checks, and each says what
it did:

* **`highsigma`** counted a failed sample using the previous sample's metric.
  On one deck, `montecarlo` reported *"10 of 60 samples failed to simulate
  and are EXCLUDED"* while `highsigma` said nothing and folded all 60 into a
  confident P(fail). The bias has a direction: with `-scale` the failures
  cluster in the **tail**, exactly the region being measured, and each is
  replaced by a more central value — so the rare-failure probability came out
  systematically **low**. It now excludes them, averages over what solved,
  and states the bias direction.
* **`wcd`** differenced its gradient against a stale value, making that
  component exactly zero. With one statistical dimension the whole gradient
  went to zero and the command announced *"the metric does not respond to any
  statistical parameter"* — blaming the model for a point the search itself
  had chosen out of range. Proven false on the same deck: at `-max 0.6` it
  finds beta = 0.3704, and only when the search steps into the failing region
  does it accuse the model. It now names what actually happened, at the
  nominal point, at an iteration, and at a gradient probe, each separately.
* **`aging`** computed a dose from a foreign bias point and then *wrote and
  persisted* it. **`emir`** reprinted a complete reliability sign-off — "0
  segments over Jmax" — on an operating point that no longer existed.
  **`loadpull`** silently entered a failed grid point as a duplicate of its
  neighbour, where the reported optimum could sit on it.

The contrast that makes the class sharp: `sweep` already did this correctly,
warning *"3 of 5 points did not converge; those points are recorded as NaN"*
and writing literal `nan`. The pattern existed; it simply had not been
applied.

## A mistyped model parameter no longer kills the session

`altermod` with a value an OSDI model's Verilog-A range refuses called
`controlled_exit(1)`. The precise conditions, measured: harmless with no
analysis yet and after `op` (the whole block is guarded by `CKTtime > 0`),
**fatal after any `dc` or `tran`** — the state a real session is almost
always in. The same refusal on an *instance* parameter (`alter`), and on any
built-in model, was only a warning. So a typo cost the user their loaded
circuit, vectors and plots, or exited a batch script with every later command
skipped. It now refuses the value and says the update did not take effect and
that the circuit wants re-setting — which is what E-531 established for
`alter`, and what the sibling string-parameter path a few hundred lines away
already did. E-534's comment shows the hazard was known: it declined to reuse
these setters for `.dc` points precisely because they "controlled_exit() on a
CKTtemp error", and that `.dc` route was verified to refuse gracefully.

## What the sampling commands were claiming

Three ways the controls did not mean what they said, all now fixed:

* **`montecarlo N` drew N−1 samples.** osdimc's first run after sourcing is
  the nominal baseline, and montecarlo spent sample 1 on it — so on a freshly
  sourced deck (the normal way to run it) one sample was deterministic while
  the banner said "N random samples", the yield and its Wilson interval
  folded that fixed point in, and the effective count depended on session
  history. It now steps past the baseline: N samples, N draws, in every
  state.
* **`-seed` did not vary the draws.** `montecarlo -seed 1` and `-seed 999`
  produced byte-identical osdimc samples, because osdimc keys on
  `.option mcseed`. Varying the seed is *the* way to check an estimate is
  stable, so every "independent" replication returned the same points and the
  result looked perfectly reproducible when nothing had been re-sampled. The
  command's own `-seed` is now mixed into the draw key — only when actually
  given, so a deck that never mentions it keeps the draws it has today.
* **`-lhs` silently did nothing** for model-declared variability. Latin
  hypercube stratifies the netlist draw functions; osdimc draws are pure
  hashes and never pass through them, so on E-530's headline deck — where
  "the netlist carries no `gauss()`/`agauss()` at all" — the flag was a no-op
  and the draws were byte-identical with and without it. It now says so.

`highsigma` also gained the degenerate-metric check `montecarlo` has had
since E-501. A metric that never varies is a mistyped node far more often
than a rare failure, and the old advice — *"increase -scale or N"* — sent the
user to spend a bigger run chasing a quantity that does not exist.

## The two E-536 regressions, and the rest

**A NULL dereference I shipped:** E-536's `sweep` interrupt poll filled the
results array at point 0, but that array is not allocated until the first
point has run (its width comes from an output list an `-output`-less sweep
only learns from that point's plot). An interrupt arriving before point 0
completed wrote NaN through a NULL pointer. It now skips straight to the
restore, with nothing recorded and nothing claimed.

**A false claim I shipped:** an interrupted `optimize` printed
"converged" — E-536 added the interrupt break straight into an unconditional
headline. E-499 had already qualified that word for three other situations;
interruption is the fourth, and it now reports "INTERRUPTED — best point so
far".

Also: **`aging`'s dose recentred an osdimc nominal**, because it applies the
dose through the `alter` *user* channel while being a machine writer — so a
statistically-declared aging parameter had the draw's randomness written
permanently into its nominal, which then random-walked across repeated aging
runs (measured 0 → 0.495253 → 0.49919 → 0.499013, non-monotonically, proving
noise rather than accumulation). Aging's writes and its E-501 replays are now
marked as machine writes, restoring E-531's rule that only what the user
typed recentres. **Result variables were never invalidated**: `$wcd_beta` and
its twenty siblings were written only on success, so after a `wcd` that
reported "cannot locate an MPFP" the previous run's `0.37037` was still
readable by the scripts these variables exist for; each command now clears
its namespace on entry. **The E-535 vector-length warning repeated per
operation** despite promising "once" — 50 identical lines from a 50-iteration
loop — and now latches. And the handbook records the one finding that is a
contract rather than a defect: under `.option osdimc` the two `sweep` engines
are separate run-class commands, so a default run and a `-perpoint` run
compare *different Monte-Carlo samples* (~2 % apart), each correct for its
own.
