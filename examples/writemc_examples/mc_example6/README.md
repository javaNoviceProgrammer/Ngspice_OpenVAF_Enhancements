# mc_example6 — `writemc` / `-writemc`: what a run produced, on the same row as the draws behind it

`mc_example5` recorded every drawn parameter per sample with `.option savemc`.
Here the results computed *from* each run go onto the same row (Enhancement-611):

- `montecarlo ... -writemc pk npk=track1.hits tpk=track1.time[0] over=maximum(v(out))-1`
  — per sample, after the tracks, specs and exprs, so an `-expr` name and a
  `track<k>.<vector>` may be listed;
- `writemc pk tr q=pk*2` — after a run in a hand-written `repeat`/`reset` loop
  (here a `meas` rise time and a `let`).

Each value must be a scalar; a column is added on first use, and a row that never
gets it is empty there — the montecarlo rows have no `tr`, the loop's rows no `npk`.

## Files

| file | what it is |
|---|---|
| `rstat.va` / `rstat.osdi` | the resistor model of mc_example5 (`(* std= *)` r and dr) |
| `writemc_demo.cir` | 200 montecarlo samples with `-writemc`, then 20 trials by hand with `writemc` |
| `mcparams_20260911_155513.csv` | what it wrote: 220 rows — the draws (`r1`, `@n1[dr]`, `@rm[r]`) and the results (`pk`, `npk`, `tpk`, `over`; `tr`, `q`) |
| `mcparams_plot.py` | `over_vs_r1.png` (overshoot against the drawn R1, coloured by the number of ringing peaks) and `tr_hist.png` (the 20 trials' rise times) |

## Run it

```
openvaf-r rstat.va -o rstat.osdi
ngspice -b writemc_demo.cir
python3 mcparams_plot.py
```

## What the file holds

```
trial,analysis,status,r1,@n1[dr],@rm[r],pk,npk,tpk,over,tr,q
1,tran,ok,24.5348205054,0.91962064256,1018.16902622,1.22587470677,2,0.000107080689285,0.225874706766,,
2,tran,ok,10.4013857186,-2.23727670569,969.632099409,1.54646928156,4,0.000100490845987,0.546469281559,,
...
219,tran,ok,26.3644909979,0,1000,1.19540329472,,,,4.847844e-05,2.39080658944
220,tran,ok,14.9493855272,0,1000,1.42281484256,,,,4.011259e-05,2.84562968513
```

Rows 1–200 are the montecarlo samples (the loop's `tr`, `q` empty), rows 201–220
the hand-run trials (the montecarlo's `npk`, `tpk`, `over` empty). Every row
already holds its values right after its run — the csv's last line is rewritten
in place, so the file is complete at every point of a long run.

Two things the example relies on: an `-expr` name is a vector of the sample's
plot (E-609), so `-writemc pk` reads the `-expr pk`; and `track1.time[0]` — the
first peak's time — reads on a sample with exactly one peak too (E-611 made
`x[0]` on a one-point vector its element; it used to be "indexing a scalar").

Enhancement-611; `verify_writemc.py` in `examples/writemc_examples/` is the test
suite. (This folder is also kept as `~/software-builds/misc/mc_example6`.)
