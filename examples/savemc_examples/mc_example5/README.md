# mc_example5 — `.option savemc`: every drawn parameter of every sample, in a file beside the deck

The RLC step response of `mc_example2`, with three kinds of statistics in the
deck — a random `.param`, a subcircuit call's own drawn value, and a
Verilog-A model whose parameters declare their variability under
`.option osdimc` — and one line that records them all:

```
.option savemc osdimc mcseed=7
```

After every analysis run `savemc` appends one row with the value in force of
every parameter that has statistics, to `mcparams_<date>_<time>.csv` in the
deck's directory. A `montecarlo` of 200 samples is 200 rows.

## Files

| file | what it is |
|---|---|
| `rstat.va` / `rstat.osdi` | a resistor whose model declares `(* std=25 *) r` (process) and `(* type="instance", std=10 *) dr` (mismatch) |
| `savemc_demo.cir` | the deck: `montecarlo 200` on `tran 2u 1m`, `.option savemc osdimc`; keeps the peak of `v(out)` per sample too (`pk.txt`) |
| `mcparams_20260911_151403.csv` | what it wrote: 200 rows × 6 drawn parameters |
| `savemc_xlsx.cir` | the same run saved as a real spreadsheet, `.option savemc=excel` → `mcparams_20260911_151405.xlsx` |
| `savemc_named.cir` | a named file (`.option savemc=loop_draws.txt`, tab-separated), a hand-written `repeat`/`reset` loop, and a run that fails → `loop_draws.txt` |
| `mcparams_plot.py` | reads the newest csv: `draws_hist.png` (every drawn parameter's distribution) and `pk_vs_r1.png` (the peak against the draw behind it) |

## Run it

```
openvaf-r rstat.va -o rstat.osdi     # the model (the .osdi is not committed)
ngspice -b savemc_demo.cir
python3 mcparams_plot.py
ngspice -b savemc_xlsx.cir      # a .xlsx
ngspice -b savemc_named.cir     # loop_draws.txt
```

## What the file holds

```
trial,analysis,status,r1,x1.c,c.x1.c1,@n2[dr],@n1[dr],@rm[r]
1,tran,ok,24.5348205054,,9.04013857186e-07,4.51220199384,0.91962064256,1018.16902622
2,tran,ok,21.1828413965,,1.18082157571e-06,13.3052107233,-2.23727670569,969.632099409
3,tran,ok,15.9771796274,,1.02835122004e-06,-8.38219382059,7.05127653696,1006.916445
```

- **`trial`, `analysis`, `status`** — the run's number, its analysis, and `ok`
  or `failed` (a run that did not solve is a row too: the draw happened —
  `loop_draws.txt` ends with a refused `dc` marked `failed`).
- **`r1`** — `R1 in a {rr}` with `.param rr = agauss(20, 30, 3)`. ngspice inlines
  a random `.param` into each use, so every use is its own draw; the column is
  named by the **slot** the draw lands in (`r1`; `m1:w` for a `w={...}` value),
  not by the `.param`.
- **`x1.c` and `c.x1.c1`** — the subcircuit call's own drawn value
  (`x1 out 0 load c={gauss(1u, 0.1, 1)}`) and the capacitor it feeds. On
  `montecarlo`'s fast path (no per-sample reset) the device slot is re-derived
  and recorded while the call's own value is not, so `x1.c` is empty on those
  rows; a `reset` loop fills both.
- **`@rm[r]`, `@n1[dr]`, `@n2[dr]`** — the OSDI model's process draw (one per
  model card per trial) and the two instances' mismatch draws, read off the
  devices after the run, so the baseline trial reports the nominal.

The histograms in `draws_hist.png` land on the declared statistics: `r1`
sd 10 (30/3), `c.x1.c1` sd 0.1 µ, `@n?[dr]` sd 10, `@rm[r]` sd 25.

## The variants

- `.option savemc=csv|txt|excel` picks the format (csv is the default; `txt`
  is tab-separated; `excel` writes a genuine `.xlsx`, rewritten every 25 rows
  and at exit). `.option savemc=<name>.<csv|txt|xlsx>` names the file, beside
  the deck.
- `.option automc_save` (alias `osdimc_save`, same values) records the OSDI
  parameters only — the automatic Monte Carlo's own draws.
- One file per deck: a `reset` continues it, a different `source` starts
  another; `nosavemc` turns it off. Two runs within one second get distinct
  names (`_2`).

Enhancement-610; `verify_savemc.py` one directory up is the test suite. (This folder
is also kept as `~/software-builds/misc/mc_example5`.)
