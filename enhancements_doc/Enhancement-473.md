# Enhancement-473 — the Monte Carlo fast path armed on a draw it could not push

`montecarlo`'s fast path (Enhancement-346) re-draws the random values and pushes
them into the live circuit instead of re-sourcing the deck for every sample. It
is only sound if **every** use of a random value is actually pushed, and the
arming check had a hole.

Only a **braced** expression is captured, and numparam decides the braces. A
quoted reference `rd='rv'` arrives at the capture pass as
`rd={(agauss(...))}` and is captured. A **bare** one — a B-source's `v=rv` —
arrives as `v= ( agauss(...) )` with no braces at all.
`sw_fp_scan_valueline()` walked past it, found no swept token, and reported the
line eligible. The fast path then armed while that value was never pushed, and a
B-source's value is substituted textually at parse time, so nothing short of a
re-source moves it: every sample after the first saw the **first** draw.

## What it cost

A 40-sample Monte Carlo whose spec depended only on the frozen value:

| | yield |
|---|---|
| fast path armed (before) | 100% or 0%, **differing between runs of the same deck and seed** |
| after this fix (disarms, re-sources) | a stable ~45–50% |

`rv ~ N(100, 60)` against a `0 ≤ v ≤ 100` spec has P = 0.452, so the sampled
answer belongs near 45%, not at either rail. The instability came from the
frozen value depending on whatever state survived between samples.

That is a silently wrong **and** unstable yield, the same family as
Enhancement-438, where a Monte Carlo counted failed samples as passes.

## Reach

The deck has to arm at all, which needs at least one *capturable* random value
alongside the uncapturable one — `.model rd='rv'` together with `B1 bs 0 v=rv`.
A bare `.param` name is not legal as an ordinary device value (ngspice rejects
`R1 a b rv` outright), so the hole is confined to expression-valued elements,
where a bare identifier is legal. A deck whose random value feeds only a
B-source never armed in the first place and was always right.

## The fix

A random draw sitting **outside any braces** is ineligible. The identifier walk
in `sw_fp_scan_valueline()` already rejects a swept token found outside a brace;
it now rejects a random call there too, so the deck disarms and takes the reset
path — slower, and right.

Decks that were always fine are untouched: a quoted random `.model` value still
arms, a braced random device value still arms, and the three ways of spelling
the same B-source value (`v=rv`, `v='rv'`, `v={rv}`) now agree.

## What this unblocked

Enhancement-472 gave the setup reuse of Enhancement-471 to `optimize` but
deliberately **not** to `montecarlo`, because the per-sample teardown was all
that limited the damage from this defect, and reusing the setup removed that
accident — the same deck and seed returned a 100% yield on one run and 0% on the
next.

With arming honest, arming means every varying value really is pushed, which is
the guarantee `sweep` already relies on. `montecarlo` keeps the circuit standing
between samples — **but only under `-warm`**, and that restriction is the point
of the next section. Every other guard is Enhancement-471's, unchanged:
`CKTtemp` still re-decides an OSDI device's node collapse and any change forces
a genuine rebuild, and the reuse is never asked for on the first sample, on the
reset path, or after a sample whose analysis failed.

Measured at 1.29× on a 1200-instance ladder, with the yield unchanged.

## Why the reuse is tied to `-warm`

Not tearing the circuit down also leaves the previous sample's **solution** in
place, which warm-starts the next one — and Enhancement-188 made that opt-in
deliberately. It keeps its guess in a buffer *outside* the `CKTcircuit`,
precisely because a reset destroys the solution, and `DCop` asks for
`MODEINITJCT` rather than `MODEINITFLOAT` when it is off.

An unconditional reuse was implemented first, and E-188's own suite caught it:
the **cold** path fell from **20606 to 1416 iterations per sample** — the
homotopy that option exists to avoid, avoided without being asked. Every yield
still matched exactly (215/215, 214/214, LHS 258/258, KLU 215/215), so nothing
was *wrong*; but a starting point is not nothing. On a circuit with more than one
operating point it decides which one a sample finds, and Monte Carlo samples are
meant to be independent draws.

Silently turning an opt-in on is the fault Enhancements 450, 451, 454 and 466
each shipped once already. So the reuse is offered exactly where the user has
already asked for state to carry between samples: under `-warm` it is pure speed
on top of what was requested, and without it nothing changes at all.

`sweep` (Enhancement-471) and `optimize` (Enhancement-472) carry the previous
solution forward for the same reason, and that is left alone: `.dc` has always
done exactly that from point to point, and warm-starting successive evaluations
is what an optimizer wants. Neither overrides a user's stated choice, because
`CKTsetWarmStart()` has only ever been driven by `montecarlo`. This is the one
place where reuse and an opt-in collide.

## Verification

`examples/mcarming_examples/verify_mcarming.py` — **20/20**, both solvers.

The headline check runs the same deck and seed five times and requires one
answer, which is exactly what the defect could not produce. Alongside it: the
bad deck no longer arms; its yield is a sampled ~45% rather than a rail; the
quoted and braced forms still arm; the three B-source spellings agree.

For the reuse half, ngspice's own report under `set ngdebug` is what pins the
decision rather than inferring it from a clock:

```
montecarlo: setup reused at 8 of 20 samples, 11 rebuilt after a node collapse moved
```

That case straddles a collapse threshold, and its spec passes only a *collapsed*
sample — so the yield measures the topology directly, and it comes back 50% with
the reuse on and off alike. A frozen topology would have reported 0% or 100%.

Two checks exist purely to hold the `-warm` line: without it, nothing is kept,
and the answer is the same either way. Enhancement-188's own suite is the other
guard — it fails if the cold path stops being cold.

`examples/reuseloops_examples/verify_reuseloops.py` (Enhancement-472) is updated:
its two checks that asserted `montecarlo` never takes the reuse now assert that
it does, so the two commands cannot drift apart.

Full regression **387/387**, both solvers. ngspice-only.
