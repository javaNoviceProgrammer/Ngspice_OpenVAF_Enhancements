# mcrecord_examples — `montecarlo` records without judging (Enhancement-552)

```
python3 verify_mcrecord.py
```

13 checks, both solvers.

## The need

The packaged Monte Carlo command answered one question: the yield. A `-spec`
was mandatory, a limit on it was mandatory, and nothing per sample survived
the run — the analyses ran under the loop commands' plot recycling — so the
plainer need, *run the sweep N times and keep a value from each*, had to be
hand-written around `reset`.

## What changed

- **A yield only where a spec has a limit.** A `-spec` without `-max`/`-min`
  is refused with a pointer to `-expr`; with no `-spec` at all there is no
  yield. Nothing to judge and nothing to record is refused too, naming both.
- **`-expr [name=]<expression>`** is evaluated after every sample and recorded
  into a plot of its own, `montecarlo1`, `montecarlo2`, … one per invocation
  (`$montecarlo_plot`), with `sample` (1 … N) as its scale:

  | the expression is | recorded as |
  |---|---|
  | a scalar per sample | an N-long vector on the `sample` scale |
  | a waveform per sample (a `dc`/`ac`/`tran` output, L points) | an N × L two-dimensional vector with the analysis scale (`v-sweep`, `frequency`, `time`) copied beside it — `plot vo` draws N curves, `vo[k]` is sample k |

  A complex value is recorded as its magnitude; a failed sample leaves `nan`;
  a waveform whose point count differs between samples is refused with the
  reason (reduce it, or `linearize` it in the `-analysis`); an expression that
  never varies is noted. The name must be a plain identifier; without one the
  vectors are `expr1`, `expr2`, …
- **`-spec` and `-expr` combine**: a yield run with `-expr` also records its
  values. The old form — a limited `-spec` alone — is unchanged and creates no
  plot.

```spice
montecarlo 200 -seed 3 -analysis op -expr vo=v(out) -expr r=@r1[resistance]
print mean(vo) stddev(vo)
pyplot -hist vo
montecarlo 50 -analysis "dc v1 0 1 0.01" -expr vo=v(out)
plot vo                                ; 50 curves
```

Where it lives: `com_montecarlo` in `src/frontend/com_sweep.c` (the parsing,
the per-sample record, the plot), `plotabs` in `src/frontend/typesdef.c` (the
`montecarlo` plot type).
