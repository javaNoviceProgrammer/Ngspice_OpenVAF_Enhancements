# Enhancement-603: a noise analysis is one analysis to its save list, and a `.print noise` card prints what each plot holds

**Scope:** `src/frontend/outitf.c` (`beginPlot`: the plot sequence of a multi-plot
analysis, the deferred unmatched-name warning, the "can't parse" line),
`src/include/ngspice/cktdefs.h` (`CKTplotsToFollow`), `src/spicelib/analysis/noisean.c`
(the count set before each plot; the integrated plot's `OUTpBeginPlot` result checked),
`src/frontend/dotcards.c` (`dotcard_on_plots`: a `.print`/`.plot` on a type with several
plots), `src/frontend/parse.c` and `src/include/ngspice/fteext.h` (`ft_pnode_item_valid`,
the quiet per-item form of `checkvalid`), `examples/noisecards_examples/` (new, 21 checks
per solver); `examples/savenoise_examples/` check [7b] re-pinned. **ngspice only; the
noise analysis and the batch flow are shared by every device.** Finding N7 of the
2026-09-10 integration hunt
([`docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md`](../docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md)),
a stock ngspice defect.

**Suites:** [`noisecards_examples`](../examples/noisecards_examples/) 21 of 21 per
solver, both solvers (19 of them fail on the unpatched tree); `savenoise` 11 of 11 with
[7b] re-pinned; `noise`, `multisave`, `saveused`, `savemiss`, `saveguard`, `savekw`,
`autosave`, `noiseloop`, `modelnoise`, `lrmnoise`, `noisefigure` unchanged; full sweep
497 of 497.

## What was wrong

```
.noise v(out) v1 dec 1 1k 10k
.print noise onoise_spectrum inoise_spectrum
```

```
Warning: can't parse 'onoise_spectrum': ignored
Warning: can't parse 'inoise_spectrum': ignored
Warning: save 'onoise_spectrum': nothing of that name is in this analysis,
         so no such vector is produced.
Warning: save 'inoise_spectrum': nothing of that name is in this analysis,
         so no such vector is produced.
Error: no data saved for Noise analysis; analysis not run
```

— and then the spectrum table printed, as asked. A noise analysis publishes **two plots
in sequence**: the spectral densities (`noise1`: `onoise_spectrum`, `inoise_spectrum`,
the per-generator densities when `pts_per_summary` is given) and the integrated totals
(`noise2`: `onoise_total`, `inoise_total`, their per-generator parts). The `.print` card
registers its names as a save restricted to the NOISE analysis, and `beginPlot` applied
that list to each plot on its own: the densities plot matched, the totals plot matched
nothing and was refused. Three things went wrong at once:

- **The totals plot was lost.** Its `OUTpBeginPlot` result was never checked in
  `noisean.c` (the densities plot's is), so the analysis went on into a run descriptor
  with no plot behind it, gave it the totals and ended it as if it were one — the third
  "No. of Data Rows" line, for a plot that does not exist.
- **The reverse card lost the whole analysis.** `.print noise onoise_total inoise_total`
  names nothing of the densities plot, which is opened first; its refusal is an error
  return, so the noise run was "not run" and "run simulation(s) aborted" — for a card
  asking for the headline result of the analysis.
- **Two warnings that were not true.** Pass 2 of `beginPlot` tries every unmatched
  restricted name as an `@dev[param]` spelling and reported the failure as "can't parse",
  which a plain vector name is not; and Enhancement-493's "nothing of that name is in
  this analysis" spoke at each plot, so a name the other plot held was reported missing.

And one level up, in `ft_cktcoms`: a `.print noise ...` card ran on **every** plot whose
type starts with `noise`, with the whole item list, so once both plots exist the card
above prints its table from `noise1` and then "Warning from checkvalid: vector
onoise_spectrum is not available or has zero length" from `noise2`; a card naming an
item of each plot, `.print noise onoise_spectrum onoise_total`, printed nothing at all,
each plot refusing the list over the item it did not hold.

## What changed

**The analysis declares its sequence.** `CKTcircuit` gains `CKTplotsToFollow`: how many
more plots the running analysis will open after the one it is opening now. `noisean.c`
sets it before each `OUTpBeginPlot` — 1 before the densities when the sweep has a span
(2 before the operating-point plot `keepopinfo` adds), 0 before the totals — and
`beginPlot` consumes it (resets it to 0), so an analysis that opens one plot need not
touch it and an analysis that fails between plots leaves nothing behind. The integrated
plot's result is checked, as Enhancement-315 did for `.disto`.

**Within a sequence, a plot the saves do not reach is kept whole.** What a save list
restricted to the analysis asks for is that analysis's output, and the other plot is the
rest of it — a handful of scalars, or a sweep of a few vectors. `.print noise
onoise_spectrum` gets both spectra printed and the totals plot whole; `.print noise
onoise_total` gets the totals printed and the densities plot whole; a `save
onoise_spectrum` before an interactive `noise` gets `noise2` too. The rule needs a save
that *applies* to the analysis — restricted to it, or unrestricted: a deck whose only
card is `.print tran v(out)` still refuses its `.noise` run "no data saved for Noise
analysis", as stock does, because nothing was asked of it.

**The unmatched-name warning speaks once, at the end of the sequence,** for the names no
plot of the sequence held. `beginPlot` keeps the unmatched names of each plot and
intersects them across the sequence (the job pointer and the declared count tell a
continuation from a fresh run); a typo gets its one warning at the totals plot, a name the
densities held gets none. The "can't parse" line is kept for the `@`-spellings
`parseSpecial` refuses and dropped for a plain name, which the unmatched-name warning
reports.

**A `.print` on a type with several plots prints from each plot what it holds.**
`dotcard_on_plots` parses the card's items quietly against each plot (`ft_pnode_item_valid`,
the per-item form of `checkvalid` without the message), prints from each plot the items it
can serve — by the items' own spelling, so an expression with spaces survives — and
reports an item no plot serves once: "`.print noise: 'nosuch' is in none of the 2 noise
plots, so it is not printed`". A `.plot` keeps its whole word list (its keywords ride
along) and is skipped on a plot that holds none of its vectors. A type with one plot, or
a `.plot` served nowhere, runs as before.

**Re-pinned:** `savenoise` [7b] held `save out` before a noise run to the stock refusal;
the run now completes, both plots whole, with `out` reported once as not in the analysis.

## Verification

| check | before | now |
|---|---|---|
| `.print noise onoise_spectrum inoise_spectrum` | two "can't parse", two "nothing of that name", totals plot refused, a third "No. of Data Rows" | the table, both plots (2 and 1 rows), silent |
| `.print noise onoise_total inoise_total` | "no data saved for Noise analysis; analysis not run", "run simulation(s) aborted" | the totals table (2.7302e-07, 5.4631e-07), silent |
| `.print noise onoise_spectrum onoise_total` | nothing printed, two "checkvalid" warnings | a table from each plot |
| `.print noise onoise_spectrum onoise_spectrun` | the run refused | the good item printed; the typo reported once at save time, once by `.print`, never as unparsable |
| `.print noise v(out)` | refused | both plots whole; `out` reported once each way |
| `.plot noise onoise_spectrum (1e-9,1e-8)` | the plot, then a "checkvalid" warning from noise2 | one ascii plot, silent |
| `save onoise_spectrum`, `noise` twice; `save onoise_total`, `noise` | noise2 refused each time; the whole run refused | noise2 whole and silent; noise1 whole, noise2 pruned to the name |
| `save out`, `tran`, `noise`; `save nosuch`, `noise` | the noise run refused | tran pruned to `out`, noise whole, the name reported once |
| single-frequency `.noise` with `.print noise onoise_spectrum` / `onoise_total` | the table / refused | the table, one plot / refused as before (no totals are published), the name reported |
| `.print tran v(out)` beside a `.noise` with no card | noise refused | unchanged: nothing was asked of it |
| `.print tran v(out)` + `.print noise onoise_total` | noise1 refused, run aborted | tran pruned, noise whole, both tables |
| `-r` rawfile with `.save onoise_spectrum` | noise2 absent from the file | noise1 pruned to the name (2 variables), noise2 written whole |
| `.option keepopinfo` + `.print noise onoise_spectrum` | refused | op plot, spectrum table, totals; silent |
| the hunt's OSDI deck (two `rc` devices, `.noise` + `.print noise` + `.ac` + `.print ac`) | as the first row | both noise plots, the ac, both tables, silent |
| `.noise ... 1` + `.print noise onoise_total_n1_thermal onoise_total` | refused | the totals table (1.9306e-07, 2.7302e-07) |

Full sweep 497 of 497 on both solvers.
