# mctrack_examples — `montecarlo -track` (Enhancements 582, 583, 584)

```
python3 verify_mctrack.py
```

21 checks, both solvers.

## The need

`track` (E-577) returns every place a condition holds — each ringing peak, each
crossing — but it is a command, not an expression: `montecarlo -expr` could not
reach it, and `-analysis "track ..."` tracked the stale plot N times, since that
flag runs exactly one command. The locator functions under `-expr` are recorded as
a family only when every sample has the same number of hits, and a *varying* count
is the point of tracking under variation.

## What changed

- **`-track "<track arguments>"`** (one quoted word, repeatable) runs `track
  <arguments>` after every sample's analysis and records the result into a plot
  of its own, `track<k>` — the shape of a `track` plot stacked over the samples:

  | vector in `track<k>` | holds |
  |---|---|
  | `sample` (the scale) | 1 … N |
  | `hits` | the hit count per sample: 0 a miss, `nan` a sample that never solved |
  | the analysis scale (`time`, `frequency`, `v_sweep`), `value`, `index`, a region's `x_out` and `width` | an Lmax × N family: row k, `time[k]`, is hit k of every sample, `nan` where a sample had fewer; plain N-long vectors when no sample has more than one hit |

- `montecarlo<n>` stays the current plot with the counts and the `-expr` vectors;
  `$track_plot` names the last record, `$track_hits` counts the samples with a
  hit. The per-sample track plots are destroyed as they are copied and the
  records take the first free `track<k>` names. A miss is silent; an error in
  the track arguments stops the run on sample 1 with the message once.
- A dc sweep's scale is spelled `v_sweep` in every track plot (E-583, E-584),
  since a hyphen in a vector name is subtraction in `let` and `print`. The fast
  path no longer runs its temperature pass before the first setup (E-583).

```spice
montecarlo 1000 -seed 3 -analysis "tran 2u 1m" -track "v(out) -spec localmax -prominence 20m" -expr r=@r1[resistance]
print mean(track1.hits)
plot track1.value[0] vs r

* a CMOS inverter's switching point and gain-region width under Vth variation
montecarlo 1000 -seed 7 -analysis "dc vin 0 3 5m" -track "v(out) -spec 'v(out) == v(in)'" -track "v(out) -spec 'abs(deriv(v(out))) > 1'" -expr vtn=@nm[vto]
plot track1.v_sweep vs vtn
setplot track2
pyplot -hist width
```
