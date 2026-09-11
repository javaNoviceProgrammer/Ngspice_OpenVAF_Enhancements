# Enhancement-611: `writemc` and `montecarlo -writemc` — values computed after a run, onto that run's row of the `savemc` file

**Scope:** `src/frontend/mcsave.c` and `mcsave.h` (`MCSAVEappend`: a value onto the last
row, the csv/txt last line rewritten in place; `com_writemc`; `MCSAVEactive`),
`src/frontend/com_sweep.c` (`com_montecarlo`: the `-writemc` flag, its items evaluated per
sample after the tracks, specs and exprs), `src/frontend/commands.c` (the command, the
help), `src/frontend/evaluate.c` (`op_ind`: element 0 of a one-point vector),
`examples/writemc_examples/` (new, 11 checks per solver; `mc_example6` beside it),
`examples/sweepguard_examples/` (one case re-classified); handbook [§3.6](../docs/handbook/03-ngspice-workflows.md). **ngspice only.** Requested by
the user, following Enhancement-610.

**Suites:** [`writemc_examples`](../examples/writemc_examples/) 11 of 11 per solver, both
solvers; `savemc`, `mcyield`, `mctrack`, `mcrecord`, `track`, `cmdfuzz`, `valguard`
unchanged; `sweepguard` re-classified one case (below); full sweep 505 of 505.

## What was asked

`.option savemc` (E-610) records the draws behind every run — one row per analysis run —
but the row is written the moment the run ends, and what a `.control` block computes from
the run (a peak, a `meas` result, a track's hit count) came after it. The user asked for a
way to append those values to the same file, and for `montecarlo` a flag doing the same
per sample.

## What changed

**The row of the last run stays addressable.** The recorder keeps every row in memory;
a value added after the run goes onto the last row, and for csv/txt that line is
rewritten in place (seek, truncate, rewrite, flush) — the file stays complete row by row,
and only the first appearance of a new column rewrites the header. The `.xlsx` is
rewritten every 25 rows and at exit, as before.

**`writemc [name=]<expression> …`** — for a `repeat`/`reset` loop, a sweep, an
interactive session: each item is a vector name or `name=expression`, evaluated on the
current plot, and must be a scalar (a vector is refused, "it has 528 points and a row
holds one number -- reduce it (maximum, mean, ...) or index it ([0])"; an undefined name
"does not evaluate"). The column is added on first use; a row that never gets it is empty
there. A name that is a draw's (`r1`) lands as `r1*` beside the draw. Before any run there
is no row to put it on, and it says so; with `.option savemc` off it says so once and
does nothing, so the same loop runs with and without recording.

```spice
.option savemc
.control
repeat 200
  reset
  tran 2u 1m
  let pk = maximum(v(out))
  meas tran tr trig v(out) val=0.1 rise=1 targ v(out) val=0.9 rise=1
  writemc pk tr overshoot=pk-1
end
.endc
```

**`montecarlo … -writemc [name=]<expression> …`** — the items up to the next flag,
evaluated for every sample after the tracks, specs and exprs, so an `-expr` name (E-609
defines it as a vector of the sample's plot), a `track<k>.<vector>` (rewritten to the
sample's plot as E-609 does) and any scalar expression may be listed:

```spice
montecarlo 200 -analysis "tran 2u 1m" -expr pk=maximum(v(out)) \
           -track "v(out) -spec localmax -prominence 20m" \
           -writemc pk npk=track1.hits tpk=track1.time[0] over=maximum(v(out))-1
```
```
trial,analysis,status,r1,pk,npk,tpk,over
1,tran,ok,24.5348205054,1.26675941714,2,0.000107825557314,0.266759417136
```

A failed sample has no values to add and its row keeps the empty cells; an item that is
not a scalar on some sample is reported once and that cell stays empty; a `track<k>`
beyond the `-track` flags given is refused at parse time; `-writemc` with `.option
savemc` off is noted once and the run proceeds without it.

**Found on the way — `x[0]` on a one-point vector.** `op_ind` refused any index on a
vector of one point ("indexing a scalar"), so `track1.time[0]` — the first hit, the
spelling a `-writemc` or a `-spec` writes once for every sample — failed on every sample
that had exactly one hit; a `-spec "track1.value[0]"` (E-609) turned into an unresolved
metric on the first such sample. Element 0 of a one-point vector is now itself (real
index 0, or the range `[0,0]`); any other index is still refused, naming the one element.
This exposed a test that had passed by accident: `sweepguard` listed `disto lin 1 1e6 1e6`
(one point, start == stop) among the sweeps that must be refused and keyed its "no output"
test on `print d[0]` — which failed only because `d` had one point. The analysis is a
legitimate single-frequency distortion run and always ran as one; the case is moved to the
suite's ordinary sweeps.

## Verification

| check | result |
|---|---|
| `-writemc pk npk=track1.hits tpk=track1.time[0] over=maximum(v(out))-1` | the four columns on every sample's row, equal to the montecarlo and track records; the one-hit sample has its `tpk` |
| `writemc pk tr q=pk*2` in a `repeat`/`reset` loop after a montecarlo | each run's row carries them; the montecarlo rows are empty there |
| `writemc pk v(out) nosuch` | the vector and the unknown name refused with their messages; `pk` on the row |
| `writemc` before any run; `-writemc` and `writemc` with `savemc` off | "no analysis has run yet"; said once each, nothing written |
| `writemc r1=@r1[resistance]` | `r1*` beside the draw's `r1` |
| `savemc=excel` | every row's value in the `.xlsx` at exit |
| `-writemc x=track2.value` with one `-track` | refused at parse time |
| the csv right after the run (`shell cp`) | every row already carries its `-writemc` value |
| `let s = 3`, `print s[0]`, `print s[1]` | 3; "its one element is [0]" |

Full sweep 505 of 505 on both solvers.
