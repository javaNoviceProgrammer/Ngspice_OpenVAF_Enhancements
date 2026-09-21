# Enhancement-688: a `.nodeset`/`.ic` on a collapsed internal node is applied to the node it collapsed into, and a `.save` of one names that node — "has no internal node" was the wrong reason

**Scope:** F6 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_ngspice-osdi-analyses-sens-and-events.md).
ngspice: `src/osdi/osdisetup.c` (`OSDIcollapsedNode`: the node an OSDI instance's internal node
was collapsed into, from the instance's node mapping), `src/include/ngspice/osdiitf.h`,
`src/spicelib/analysis/cktsetnp.c` (the deferred `.ic`/`.nodeset` placed on that node, with a
Note), `src/frontend/outitf.c` (the save warning names it). `examples/internalnode_examples/`
(three checks, 19). **ngspice only.**

**Suites:** [`internalnode_examples`](../examples/internalnode_examples/) 19 of 19 per solver,
both solvers (all 3 new checks fail on the E-680 binaries, beside E-681's three); full sweep
531 of 531.

## What was wrong

A model that collapses an internal node when a parameter is zero:

```verilog
module colres(a, c); inout a, c; electrical a, c, ai;
  parameter real rs = 0 from [0:inf);
  analog begin
    if (rs > 0) I(a, ai) <+ V(a, ai) / rs; else V(a, ai) <+ 0;
    ...
```

builds no node `n1#ai` at setup: `ai` *is* `a`. [E-608](Enhancement-608.md) defers a `.ic` or
`.nodeset` on `<instance>#<node>` to setup and places it once the device has built the node; a
node the device did not build was refused as

```
Warning : Nodeset on non-existent node - n1#ai, ignored
   (n1 has no internal node 'ai')
```

which is the wrong reason — `n1` declares `ai`, the model collapsed it — and `.save v(n1#ai)`
said "nothing of that name is in this analysis", with no hint that `v(a)` carries it; a `.save`
list that emptied this way stopped the analysis ("no data saved").

## What changed

**`OSDIcollapsedNode(ckt, "n1#ai", &into)`** finds the instance, looks the suffix up among the
descriptor's internal nodes, and returns the global number of the node it was collapsed into
from the instance's node mapping (0 for ground or an unconnected node); 0 when the name is no
internal node of an OSDI instance. It is valid once setup has run, which is when both callers ask.

**The deferred `.ic`/`.nodeset` is applied to that node**, at every setup as E-608's placement
is, with a Note once: "Nodeset on n1#ai: the model collapses n1's internal node 'ai' into 'a',
so it is applied to 'a'." A node collapsed into ground is reported and ignored. A name that is no
internal node keeps the old refusal, whose reason is right for it.

**The save warning names the node**: "save 'n1#ai': the model collapses n1's internal node 'ai'
into 'a', so no such vector is produced; save v(a) instead." (Two spellings of one node would be
two vectors of one value; the pointer is the honest answer.)

## Verification

| check | result |
|---|---|
| `.nodeset v(n1#ai)=0.5` on the collapsed node, `op` | the Note names `a`; no "non-existent"; the op at 1.0 V as before |
| `.ic v(n1#ai)=0.3` under `tran … uic` | the Note; `v(a)` starts at 0.3 (was ignored) |
| `.save v(a) v(n1#ai) v(n1#zz)` | the `n1#ai` warning names `a` and suggests `v(a)`; `n1#zz` keeps "nothing of that name"; the analysis runs |
| `.ic v(n1#zz)` | "IC on non-existent node … (n1 has no internal node 'zz')", unchanged |
| the E-680 binaries on the suite | all 3 new checks fail |
| full sweep | 531 of 531 |

## What this does not do

- A `.save` list every entry of which is refused still stops the analysis with "no data saved":
  with nothing to record there is nothing to run for, and the warnings above it say why each name
  was refused.
- A collapsed node gets no vector of its own; `v(a)` is the value. Aliasing the two names would
  be a `.save` feature, not a placement fix.
