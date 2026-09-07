# mctrack_examples — `montecarlo -track` (Enhancement-582)

```
python3 verify_mctrack.py
```

20 checks, both solvers.

## The need

`track` (E-577) returns every place a condition holds — each ringing peak, each
crossing — but it is a command, not an expression: `montecarlo -expr` could not
reach it, and `-analysis "track ..."` tracked the stale plot N times, since that
flag runs exactly one command. The locator functions under `-expr` are recorded as
a family only when every sample has the same number of hits, and a *varying* count
is the point of tracking under variation.

## What changed

- **`-track "<track arguments>"`** (one quoted word, repeatable) runs `track
  <arguments>` after every sample's analysis and records the result in the
  `montecarlo<n>` plot beside the `-expr` vectors:

  | vector | holds |
  |---|---|
  | `track_hits` | the hit count per sample: 0 a miss, `nan` a sample that never solved |
  | `track_<vector>` — the scale, `value`, `index`, a region's `x_out` and `width` | an Lmax × N family: row k, `track_time[k]`, is hit k of every sample on the `sample` scale, `nan` where a sample had fewer; plain N-long vectors when no sample has more than one hit |

- Several `-track` flags record as `track1_*`, `track2_*`; `-track` combines with
  `-spec` and `-expr`. The per-sample track plots are destroyed as they are
  recorded. A miss is silent; an error in the track arguments stops the run on
  sample 1 with the message once, recording nothing.
- A dc sweep's scale is `v-sweep`; it records as `track_v_sweep` (E-583), since a
  hyphen in a vector name is subtraction in `let` and `print`.

```spice
* a CMOS inverter's switching point and gain-region width under Vth variation
montecarlo 1000 -seed 7 -analysis "dc vin 0 3 5m" -track "v(out) -spec 'v(out) == v(in)'" -track "v(out) -spec 'abs(deriv(v(out))) > 1'" -expr vtn=@nm[vto]
plot track1_v_sweep vs vtn
pyplot -hist track2_width
```

```spice
montecarlo 1000 -seed 3 -analysis "tran 2u 1m" -track "v(out) -spec localmax -prominence 20m" -expr r=@r1[resistance]
print mean(track_hits)
plot track_value[0] vs r
```
