# Enhancement-473 — the Monte Carlo fast path armed on a draw it could not push

```
python3 verify_mcarming.py
```

20 checks, both linear solvers.

## What was wrong

`montecarlo`'s fast path (Enhancement-346) re-draws the random values and pushes
them into the live circuit instead of re-sourcing the deck per sample. That is
sound only if **every** use of a random value is pushed, and the arming check
had a hole.

Only a **braced** expression is captured, and numparam decides the braces: a
quoted `rd='rv'` arrives as `rd={(agauss(...))}` and is captured, but a bare
`v=rv` in a B-source arrives as `v= ( agauss(...) )` with no braces at all. The
scanner walked past it and called the line eligible — so the fast path armed
while that value was never pushed, and a B-source's value is substituted
textually at parse time, so nothing short of a re-source moves it.

Every sample after the first saw the **first** draw:

| 40 samples, spec depends only on the frozen value | yield |
|---|---|
| before | 100% or 0%, **differing between runs of the same deck and seed** |
| after | a stable ~45–50% |

`rv ~ N(100, 60)` against `0 ≤ v ≤ 100` has P = 0.452, so the answer belongs near
45%, not at a rail. A silently wrong *and* unstable yield — the same family as
Enhancement-438, where a Monte Carlo counted failed samples as passes.

## Reach

The deck must arm at all, which needs a capturable random value alongside the
uncapturable one (`.model rd='rv'` plus `B1 bs 0 v=rv`). A bare `.param` name is
not legal as an ordinary device value — ngspice rejects `R1 a b rv` — so the
hole is confined to expression-valued elements, where a bare identifier is legal.

## The fix

A random draw outside any braces is ineligible. The identifier walk already
rejected a *swept* token found outside a brace; it now rejects a random call
there too, so such a deck disarms and takes the reset path.

Checks `[4]`–`[6]` are the ones that keep the fix narrow: the quoted and braced
forms still arm, and `v=rv`, `v='rv'` and `v={rv}` — the same circuit written
three ways — now agree.

## What it unblocked

Enhancement-472 gave `optimize` the setup reuse of Enhancement-471 but withheld
it from `montecarlo`, because the per-sample teardown was all that limited the
damage from this defect. With arming honest, `montecarlo` keeps the circuit
standing too (1.29× on a 1200-instance ladder, yield unchanged) — **but only
under `-warm`**.

That restriction is not caution for its own sake. Not tearing the circuit down
leaves the previous sample's *solution* in place, which warm-starts the next
one, and Enhancement-188 made that opt-in deliberately. An unconditional reuse
cut E-188's **cold** path from 20606 to 1416 iterations per sample — its opt-in,
turned on without being asked. The yields all still matched, but a starting
point decides which operating point a sample finds on a circuit that has more
than one. Checks `[9]`/`[10]` hold that line.

The decisive check straddles a node-collapse threshold with a spec that passes
only a *collapsed* sample, so the yield measures the topology directly:

```
montecarlo: setup reused at 8 of 20 samples, 11 rebuilt after a node collapse moved
```

50% with the reuse on and off alike. A frozen topology would have said 0% or
100%.
