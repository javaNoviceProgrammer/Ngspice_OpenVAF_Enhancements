# Enhancement-609: `montecarlo` — the yield of a tracked quantity, in one command: an `-expr` feeds a `-track` or a `-spec`, and a `-spec` or `-expr` reads the track

**Scope:** `src/frontend/com_sweep.c` (`com_montecarlo`: the exprs in two passes around
the tracks, an expr defined as a vector of the sample's plot; each sample's track plot
kept until the specs and exprs have read it; `mc_track_refs`, the `track<k>.<vector>`
rewrite; `mc_expr_sample`; the parse-time check; the report),
`examples/mcyield_examples/` (new, 14 checks per solver); handbook
[§3.3](../docs/handbook/03-ngspice-workflows.md). **ngspice only.** Reported by the
user: "I can't combine `-expr`, `-track`, `-analysis` and `-spec` in one `montecarlo`
command to find the yield of a tracked expression" — and, asked next, whether an
`-expr` can feed a `-track` whose `-output` names the value a `-spec` then judges.

**Suites:** [`mcyield_examples`](../examples/mcyield_examples/) 14 of 14 per solver,
both solvers; `mctrack`, `mcrecord`, `mcpolicy`, `mcarming`, `mcfastpath`, `track`
unchanged; full sweep 503 of 503.

## What was wrong

The four flags were accepted together, and `-expr` and `-track` recorded as they
should — but a `-spec` was evaluated on the analysis plot, before the tracks ran, so
nothing in it could reach a track's result:

```
montecarlo 40 -analysis "dc v1 0 5 0.01" -track "v(out) -spec globalmax" -spec value -min 2
montecarlo: spec 1 (value) did not resolve to a value on sample 1 -- it names no vector
this analysis produces ...
```

`-spec track1.value` fared the same (`track1` is the record plot, which exists only
after the run). The locators as functions (`-spec "globalmax(v(out))" -max 2`) covered
the plain cases, and only those: a track's `-prominence`, `-edge`, `-which`, a region's
`x_out` and `width`, have no expression form. The yield of a tracked quantity was a
hand-written `repeat` loop with `$track_plot` and `$track_hits`.

## What changed

- **The tracks run first**, and each sample's track plot is kept until the specs and
  exprs have read it, then destroyed as before.
- **`track<k>.<vector>` in a `-spec` or `-expr`** names the k-th `-track` of the
  command, for the sample being judged: `track1.value`, `track2.x_out`,
  `track1.value[0]` (the first of several hits; a bare `track1.value` judges the last,
  as any metric takes its last element), and `track1.hits`, the hit count as a number —
  0 on a miss, which no plot could say. The per-sample plot has a global number
  (`track37`), different every sample, so the metric is rewritten before it is
  evaluated: `track<k>.` becomes that plot's own name. The record plots made at the end
  are `track<k>` in the same order, so the spelling means the same thing before and
  after the run. A metric may mix the two plots: `track1.v_sweep / maximum(v(out))`.
- **A miss.** A spec on a track that had no hit for the sample is a violation — the
  thing judged is not there — counted apart in the report: "spec 1 (track1.width): 24
  violations (23 of them samples whose track had no hit to judge)". `-spec track1.hits
  -max 0` is the yield of "nothing there". An `-expr` on a missed track leaves nan for
  that sample, with a NOTE; one that never hit is not recorded, and says so.
- A `track<k>` beyond the `-track` flags given is refused at parse time: "-spec
  'track2.value' reads track2, but only one -track was given -- the k in
  track<k>.<vector> is the -track's position in this command".
- **An `-expr` feeds a `-track` or a `-spec`.** An `-expr` that does not read a track is
  evaluated *before* the tracks and defined as a vector of that name in the sample's
  analysis plot, so the track's expression and a spec may use it by name; an `-expr`
  that does read a track is evaluated after them. The whole chain composes:

  ```
  montecarlo 200 -analysis "dc v1 0 5 0.01" -expr q=v(out)*2 \
             -track "q -spec globalmax -output pk" -spec "track1.pk" -min 4
  ```

  A `-spec qmax -min 4` straight on an `-expr qmax=...` works the same way. An `-expr`
  named like a vector the analysis plot already holds is left to the plot, and says so
  once ("a -track or -spec naming 'out' reads the plot's, not the -expr").

```
montecarlo 200 -analysis "dc v1 0 5 0.01" -track "v(out) -spec globalmax" \
           -expr pk=maximum(v(out)) -spec "track1.value" -min 2
```

## Verification

| check | result |
|---|---|
| `-analysis`, `-track`, `-expr`, `-spec track1.value -min 2` | 30 / 40 pass — the same as `-spec maximum(v(out)) -min 2`; the count equals the record's own; the `-expr` recorded beside it |
| `-spec "track1.v_sweep / maximum(v(out))" -max 0.7` | the pass count matches a recount from the records (25) |
| a region track with misses, `-spec track1.hits -max 0` | 23 / 40: the yield of "no region" (17 hits) |
| `-spec track1.width -min 0.5` on it | "(23 of them samples whose track had no hit to judge)"; the passes recounted (16) |
| `-expr w=track1.width` | nan on the 23 misses, with a NOTE; equal to the record's width on the 17 hits |
| a multi-hit track, `-spec track1.value[0] -min 2.2` | the first hit judged; 29 / 30, matching the record's recount |
| two `-track` flags, `-spec track2.value`, `-expr dip=track2.value` | the second read |
| `track2.` with one `-track`; `track1.` with none; an `-expr`'s `track3.` | refused at parse time |
| `-spec maximum(v(out))` without a track; `-expr` beside `-spec` | unchanged |
| `-expr q=v(out)*2`, `-track "q -spec globalmax -output pk"`, `-spec track1.pk -min 4` | 30 / 40 (the peak ≥ 2 V); the record holds `pk` |
| `-expr qmax=maximum(v(out)*2)`, `-spec qmax -min 4` | 30 / 40 |
| `-expr pkv=track1.pk` on the track that read `q` | equal to the record on every sample |
| `-expr out=...` (a vector the plot holds) | the note, once; the spec reads the plot's |

Full sweep 503 of 503 on both solvers.
