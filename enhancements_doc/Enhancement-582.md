# Enhancement-582: `montecarlo -track "<track arguments>"` — `track` runs after every sample's analysis and its hits are recorded per sample

> **Superseded in part by [E-584](Enhancement-584.md).** The record is now a plot of
> its own, `track<k>`, holding `sample`, `hits`, `time`, `value`, … under their own
> names; the prefixed `track_*` vectors inside `montecarlo<n>` described below no
> longer exist. The flag, the per-sample run, the hit-major layout and the quiet and
> error hooks are as described here.

**Scope:** `src/frontend/com_sweep.c` (the flag, the per-sample run, the record),
`src/frontend/com_track.c`/`com_track.h` (a quiet mode and an error flag for the
caller), `src/frontend/commands.c` (help), statistics guide §6.2, the commands table,
handbook §3.3 and §3.6, `examples/mctrack_examples/` (new, 17 checks per solver).
**ngspice only.**

**Suites:** [`mctrack_examples`](../examples/mctrack_examples/) 17 of 17 per solver,
both solvers; [`track_examples`](../examples/track_examples/) and
[`mcrecord_examples`](../examples/mcrecord_examples/) unchanged; full sweep 480 of 480.

## The question it answers

"Can't we do `montecarlo 1000 -seed 3 -analysis "track v(a) -spec localmin"`?" No,
and measured: `-analysis` runs exactly one command, so that form ran no analysis and
`track`ed the stale plot a thousand times, giving a thousand identical answers; `-analysis
"tran 2u 1m; track ..."` is not two commands either, it is a `tran` with junk arguments.
E-581 had settled the combination on a hand-written `repeat` loop, and E-552's `-expr`
records the locator *functions* — but a locator's vector of positions is recorded only
when every sample has the same number of hits, and a varying count is the whole point of
tracking under variation: how many ringing peaks, and where, as a resistor is drawn.

## What changed

`montecarlo` takes **`-track "<track arguments>"`** — one quoted word, because `track`'s
own options begin with `-`; repeatable, up to eight. After every sample's analysis (and
after that sample's `-expr` evaluation) the command runs `track <arguments>` on the
sample's plot, quietly, and records the result into the `montecarlo<n>` plot beside the
`-expr` vectors:

| vector | holds |
|---|---|
| `track_hits` | the hit count per sample on the `sample` scale: 0 a miss, `nan` a sample that never solved |
| `track_<vector>`, one per vector of the track plot — the scale (`time`, `frequency`, …), `value`/`value1..N`/the `-output` names, `index`, a region's `x_out` and `width` — each with the source vector's type | an Lmax × N family, *hit-major*: row k is hit k of every sample on the `sample` scale, `nan` where a sample had fewer, Lmax the largest count any sample had; plain N-long vectors when no sample ever has more than one hit |

A dc sweep's scale `v-sweep` records as `track_v_sweep` ([E-583](Enhancement-583.md):
a hyphen in a vector name is subtraction in `let` and `print`).

The orientation is the opposite of E-552's waveform families (`vo[k]` there is sample
k's curve) because the Monte Carlo question about hits is a different one: not "what did
sample k do" but "where did the *second* peak land across the samples". So `track_time[1]`
is the second hit of every sample, N long on the `sample` scale, `nan` where there was
none; `plot track_value[0] vs r` puts the first peak's height against the resistance
`-expr` recorded beside it; `track_time[k][i]` is sample i's k-th hit; and `plot
track_time` draws Lmax curves against `sample`. Several `-track` flags record as `track1_*`, `track2_*`; `-track`
combines with `-spec` (the yield is reported too) and `-expr`, and with `-lhs`/`-warm`;
alone it is a record-only run like a lone `-expr`. The per-sample track plots are
destroyed as they are recorded (`$track_plot`/`$track_hits` are left with the last
sample's result); the summary says how many samples had a hit, the largest count, and
the family shape, and notes a `-track` that never hit.

Two small hooks in `track` make this clean. **`track_quiet`** suppresses the per-call
summary and batch rows — N copies of them would be noise — and makes a miss silent (it
is a normal outcome here, recorded as 0), while `$track_plot`/`$track_hits` are still
set. **`track_error`** is raised by every failure *other* than a miss (an expression
that does not evaluate, an unknown option, a spec of the wrong kind), and `montecarlo`
stops on it at the first sample with the message once and records nothing, instead of
repeating the error a thousand times. A `-track` without its quoted argument, or with an
empty one, is refused showing the form; "nothing to do" now names `-track` beside
`-spec` and `-expr`.

```spice
.param rr = agauss(20, 30, 3)
V1 in 0 pulse(0 1 0 1n 1n 1m 2m)
R1 in a {rr}
L1 a out 1m
C1 out 0 1u
.control
  montecarlo 1000 -seed 3 -analysis "tran 2u 1m" -track "v(out) -spec localmax -prominence 20m" -expr r=@r1[resistance]
  print mean(track_hits)          ; ringing peaks per sample
  pyplot -hist track_time[1]      ; where the second peak lands
.endc
```

## Verification

The suite runs the RLC step response above, seeded, on both solvers:

| check | result |
|---|---|
| the record | `track_hits` equals `length(localmax(v(out)))` recorded by `-expr` on every sample; with `-raw` the first tracked peak equals `globalmax(v(out))` exactly |
| the families | `[Lmax,8]` dims with Lmax the largest count; each sample's column holds exactly its hits, increasing in time, then `nan`; `track_time[1]` is the second hit of every sample, 8 long; `value` carries the voltage type and every first peak is an overshoot |
| a region with `-which first` | plain 8-long vectors, `x_out` and `width` present, `width == x_out − time` on every sample |
| two `-track` flags | `track1_*` and `track2_*`, each with its own count (one more maximum than minima at 20 mV prominence on a step) |
| misses | silent, 0 with an all-`nan` row; a spec that never hits is noted and records zeros; `$track_plot`/`$track_hits` hold the last sample's result; no `track` plot survives the run |
| an argument error | stops on sample 1 with the message once, nothing recorded, `$montecarlo_plot` unset (`v(nosuch)`, and an unknown option) |
| refusals | `-track` without its argument (the quoted form shown), an empty one; "nothing to do" names `-track` |
| with a yield | a limited `-spec`, `-lhs` and `-track` together: the yield line and the record; a lone `-track` is a record-only run |
