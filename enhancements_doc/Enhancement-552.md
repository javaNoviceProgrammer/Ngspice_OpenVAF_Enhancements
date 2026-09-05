# Enhancement-552: `montecarlo -expr` records a value per sample into a `montecarlo<n>` plot, and a yield is judged only where a spec has a limit

**Scope:** the packaged Monte Carlo command, `montecarlo`
(`src/frontend/com_sweep.c`), its help text and the plot-type table.
**ngspice only; the compiler is unchanged.**

**Suites:** [`mcrecord_examples`](../examples/mcrecord_examples/) (new, 13
checks, both solvers); the 22 suites that use `montecarlo` pass unchanged;
`plotorder` accepts the new plot type. Statistics guide
[§6.1](../docs/internals/ngspice_internals/ngspice_statistics.md), handbook
[§3.6](../docs/handbook/03-ngspice-workflows.md), the
[commands table](../docs/internals/ngspice_internals/ngspice_commands.md) and
`help montecarlo` describe both forms.

## What was wrong

The command answered one question, the yield. A `-spec` was mandatory, a
limit on it (`-min` or `-max`) was mandatory, and nothing per sample survived
the run: the analyses run under the loop commands' plot recycling, so "run
the sweep N times and keep a value from each" had to be hand-written around
`reset`.

## What changed

* **`-expr [name=]<expression>`** is evaluated after every sample and
  recorded, unjudged, into a plot of its own — `montecarlo1`, `montecarlo2`,
  … one per invocation, named in `$montecarlo_plot` — with `sample` (1..N)
  as its scale. Several `-expr` flags make several vectors in the same plot.
* **A scalar per sample** is an N-long vector. **A waveform per sample** (a
  dc, ac or tran output of L points) is an N × L two-dimensional vector with
  the analysis scale copied beside it, which `plot` draws as a family and
  `vo[k]` indexes as sample k. A complex value is recorded as its magnitude;
  a failed sample is `nan`.
* **The yield is judged only where a spec has a limit.** A `-spec` without
  `-min`/`-max` is refused with a pointer to `-expr`; with no `-spec` there
  is no yield report; nothing to judge and nothing to record is refused
  naming both. `-spec` and `-expr` combine, giving the yield and the record.
  A limited `-spec` alone is unchanged and creates no plot.
* A waveform whose point count differs between samples is refused with the
  reason, the scalars beside it still recorded; an expression that never
  varies is noted; one that resolves to nothing is refused on sample 1.
* `montecarlo` is registered as a plot type (`typesdef.c`): the plots came
  out as `unknown1` without it.

```spice
montecarlo 40 -seed 7 -analysis "ac dec 10 10 100k" -expr gain=db(v(out))
+ -expr fc=1/(2*pi*@r1[resistance]*@c1[capacitance])
setplot $montecarlo_plot
plot gain            $ the 40-member family against frequency
pyplot -hist fc      $ the corner-frequency histogram
```

## Verification

| check | result |
|---|---|
| a record-only run | no yield line; three scalars recorded; `$montecarlo_plot` names the plot |
| the recorded values | each sample's own: `r` drawn from the deck's `.param` |
| a dc sweep's output | an N × L family with the v-sweep scale beside it |
| an ac output | recorded as its magnitude, on the frequency scale |
| two invocations | two plots; the first still readable |
| the family | renders through `pyplot` |
| a `-spec` without a limit | refused, naming `-expr` |
| nothing to judge and nothing to record | refused, naming both |
| an `-expr` that resolves to nothing | refused; nothing recorded |
| a limited `-spec` and `-expr` together | the yield and the record |
| an expression that never varies | noted |
| a waveform whose point count differs between samples | refused with the reason; the scalars beside it recorded |
| the old form | a limited `-spec` alone reports the yield and creates no plot |
| `mcrecord_examples` | 13 / 13, both solvers |
| full sweep | 456 of 456 |
