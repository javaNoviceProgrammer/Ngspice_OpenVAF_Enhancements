# Enhancement-584: `montecarlo -track` records into a plot of its own, `track<k>` — `sample`, `hits`, `time`, `value`, … under their own names

**Scope:** `src/frontend/com_sweep.c` (the record), `src/frontend/vectors.c` and
`include/ngspice/fteext.h` (`plot_typenum_forget`), `src/frontend/com_track.c` (a dc
sweep's scale spelled `v_sweep` in the track plot), `src/frontend/commands.c` (help),
statistics guide §6.2, the commands table, handbook §3.3 and §3.6,
`examples/mctrack_examples/` (rewritten, 21 checks per solver), `examples/track_examples/`
(one check reworded). **ngspice only.**

**Suites:** [`mctrack_examples`](../examples/mctrack_examples/) 21 of 21 per solver,
[`track_examples`](../examples/track_examples/) 40 of 40 per solver, both solvers;
full sweep 480 of 480.

## The point that was made

E-582 recorded a `-track` as vectors inside `montecarlo<n>`, prefixed to keep them
apart: `track_hits`, `track_time`, `track_value`, and `track1_*`, `track2_*` with
several flags. The question that changed it: *why not a plot called `track1` with
those vectors bundled into it?* A `track` result already has a shape — a scale,
`value`, `index`, a region's `x_out` and `width` — and the Monte Carlo record is that
shape stacked over the samples. Prefixing every vector and crowding it into the
`-expr` plot was the wrong container.

## What changed

Every `-track` is now **a plot of its own, `track<k>`**, named "Monte Carlo track:
<arguments>":

| vector | holds |
|---|---|
| `sample` (the scale) | 1 … N |
| `hits` | the hit count per sample: 0 a miss, `nan` a sample that never solved |
| the analysis scale (`time`, `frequency`, `v_sweep`), `value` / `value1..N` / the `-output` names, `index`, `x_out`, `width`, `edge` — each with its type | Lmax × N, hit-major: row k is hit k of every sample, `nan` where it had fewer; plain N-long vectors when no sample had more than one hit |

So `track1.time[1]` is the second hit of every sample and `plot track1.value[0] vs r`
puts the first peak against a parameter `-expr` recorded — the same layout as E-582,
under the names `track` itself uses. Around it:

* **Numbering.** ngspice numbers plots per type from the last number handed out, so
  after a thousand per-sample `track` plots — made and destroyed as they were copied
  — the record would have been `track1000`. A new `plot_typenum_forget(type)` in
  `vectors.c` drops that memory; `montecarlo` calls it once the per-sample plots are
  gone, and the records take the first free names, `track1`, `track2`, …. A later
  standalone `track` numbers on from there.
* **What is current.** `montecarlo<n>` stays the current plot — it holds the run's
  counts (`montecarlo_n`, `montecarlo_nvalid`, the yield) and the `-expr` vectors, and
  `$montecarlo_plot` names it — so a record is reached as `track1.value` from there
  or with `setplot $track_plot`. After the command `$track_plot` names the last record
  made and `$track_hits` counts the samples that had a hit (E-581's per-call meaning
  would have named a destroyed plot).
* **The summary** names the plot and its vectors: `-track "...": hits in 6 of 8
  samples, at most 4 per sample -- plot track1: sample, hits, time, value, index
  ([4,8] families: row k is hit k of every sample, nan where it had fewer)`; a
  `-track` that never hit gets a plot of zeros and says so; a `-track`-only run says
  where the counts are and how the record is reached.
* **`v_sweep` everywhere.** E-583 had spelled a dc sweep's scale `track_v_sweep`
  because `v-sweep` is a subtraction to `print`. That holds for `track`'s own plot
  too — `print track1.v-sweep` never worked — so the standalone track plot now names
  its dc scale `v_sweep` as well, and its rows say `v_sweep=1.5`.

```spice
montecarlo 1000 -seed 3 -analysis "tran 2u 1m" -track "v(out) -spec localmax -prominence 20m" -expr r=@r1[resistance]
print mean(track1.hits)              ; ringing peaks per sample
plot track1.value[0] vs r            ; the first peak's height against the resistance
setplot $track_plot
pyplot -hist time[1]                 ; where the second peak lands
```

## Verification

The suite was rewritten for the new names and gained a check on the plot itself:

| check | result |
|---|---|
| the record | `montecarlo1` current, `$track_plot` = `track1`; `track1.hits` equals `length(localmax(v(out)))` per sample; the first `-raw` hit equals `globalmax` |
| the plot | named "Monte Carlo track: …", holds exactly `sample` (default scale), `hits`, `time`, `value`, `index`; `[Lmax,8]` families; `montecarlo1` holds the `-expr` vectors and counts and no track vector |
| the columns | each sample's column holds exactly its hits, increasing, then `nan`; `time[1]` is row 1; `value` voltage-typed, every first peak an overshoot |
| a region with `-which first` | plain 8-long vectors, `x_out` and `width` present, `width == x_out − time` |
| two `-track` flags | plots `track1` and `track2` with their own counts; `$track_plot` = `track2` |
| misses and numbering | a miss is silent, 0 with an all-`nan` column; `$track_hits` counts the samples with a hit; a spec that never hits makes a plot of zeros; the records are `track1` and `track2` with no per-sample plot left; a later standalone `track` is `track3` |
| errors, refusals, a yield, a lone `-track` | as in E-582; a lone `-track` leaves `montecarlo1` current and says how the record is reached |
| a dc sweep | the scale is `v_sweep` in `track1`/`track2`, printed across plots; the switching point per sample equals (vtn + VDD + vtp)/2 within 20 mV; the region's `width == x_out − entry`; no spurious "Phi is not positive" (E-583) |
