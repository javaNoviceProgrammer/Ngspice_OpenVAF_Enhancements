# Enhancement-666: the `autocorner` follow-on gaps — a raw-file `run` keeps every corner's plot, `meas` and `writemc` read the combined plot, the corner copies keep their accessor readable, and the devices follow the `corner` variable when a loop ends

**Scope:** F8 of the
[bug hunt of 2026-09-18](../docs/bug_hunts/2026-09-18_openvaf-r-corners-and-run-control.md).
ngspice: `src/frontend/com_sweep.c` (`autocorner_run`: the raw-file pass, the
plot families, `ac_copy_name`; `com_corners`), `src/frontend/runcoms.c`
(`raw_open_for_run`), `src/frontend/outitf.c` (`fileInit`: the plot name in
the file), `src/include/ngspice/plot.h` (`pl_kind`), `src/frontend/postcoms.c`,
`src/frontend/measure.c` and `com_measure2.c` (the analysis check reads
`pl_kind`), `src/frontend/mcsave.c` (`MCSAVEappendPlot`, `com_writemc` on a
combined plot), `src/osdi/osdisetup.c` (`OSDImcCornerLeave`),
`src/include/ngspice/osdiitf.h`, `src/frontend/com_sweep.h`, `mcsave.h`.
`examples/autocorner_examples/` (six checks added, one reworded, 21 per
solver). Handbook [§3.7](../docs/handbook/03-ngspice-workflows.md).
**ngspice only.**

**Suites:** [`autocorner_examples`](../examples/autocorner_examples/) 21 of 21
per solver, both solvers (9 of 21 fail on the E-661 binaries); `cornerscmd`,
`savemc`, `writemc`, `vacorner`, `mcyield`, `lrmcorner`, the four `meas*` and
the four `raw*` suites, `osdireload` unchanged; full sweep 530 of 530.

## What was wrong

[E-656](Enhancement-656.md) made `.option autocorner` run every run-class
command at the nominal and at every declared corner, and built the combined
`autocorner<n>` plot a schematic host draws. Five things around that pass
were left unfinished, and the hunt listed them together:

| | what happened |
|---|---|
| `run n5.raw` | each corner wrote the raw file, which holds the last corner alone; the loop then said `autocorner: corner tt: the run made no plot` three times, for runs that had succeeded into the file |
| `meas tran` after an `autocorner` transient | *Error: meas tran: the current plot is 'autocorner1', not a tran analysis* — the plot that holds `v(out_ss)` cannot be measured, and a `setplot tran2` reaches a plot that holds no corner vector |
| `writemc` after an `autocorner` run | *the current plot autocorner1 was made after row 3 by a run that has no row; nothing is put on that row* — the combined plot is nobody's run |
| the copies of `@rm[rsh]` and `v1#branch` | named `@rm[rsh]_ss` and `v1#branch_ss`: a bare `print @rm[rsh]_ss` read the parameter and a stray `_ss`, `let` refused the name, only the quoted form reached the 115; and `i(v1_ss)`, the banner's own example, was "not available" (it looks for `v1_ss#branch`) |
| after the loop | `showmod rm` showed `rsh 88`, the `ff` value, with no corner in force and the combined plot current — the devices stayed at the last corner until the next run re-read the variable |

## What changed

- **A raw-file `run` keeps every corner.** The corners after the first open
  the file at its end (`r+` and a seek, not append mode: the writer seeks
  back to patch the point count, and an append-mode stream would send that
  patch to the end too), and inside the pass the file's `Plotname:` carries
  the corner, as the in-memory plots do — `Transient Analysis (corner ss)`.
  The file holds one plot per corner; `load n5.raw` reads them all, and the
  banner says so. No combined plot is built for a file; `$autocorner_n` and
  `$autocorner_names` are set, `$autocorner_plots`/`$autocorner_plot` are not.
  The batch `-r file` path is the same `run`. A corner whose run failed is
  now said as *the run failed* (it was *made no plot* whether it failed or
  not).
- **`meas` reads the combined plot as its nominal's analysis.** A plot gains
  `pl_kind`, the analysis plot a derived plot stands for; the combined plot
  carries its nominal's typename (`tran1`), and the two analysis checks
  (`meas <an>` against the current plot, E-491's, and *measure limited to
  tran, dc, sp, or ac*) read it. The combined plot's scale is the nominal's,
  so `meas tran a find v(out_ss) at=200u` answers off the right axis; `ac`
  and `dc` likewise. An `op` pass stays unmeasurable, as an `op` plot is.
- **`writemc` on the combined plot serves every corner's row.** The pass
  made one `savemc` row per corner (E-655). On the combined plot each item
  is evaluated on every corner's own plot and put on that corner's row —
  `writemc y=v(out)` gives the tt row the nominal's value, the ss row the ss
  plot's, the ff row the ff plot's — said once per plot. A name only the
  combined plot holds (`v(out_ss)`) fails on each and gets the hint that a
  corner's own plot holds its vectors under their plain names. Behind it,
  `MCSAVEappendPlot` writes onto the latest row whose run made a given plot,
  rewriting the file when the row is not the last.
- **The copies keep their accessor readable.** The suffix goes on the node or
  device name, not on the end of the vector's name: `out_ss`, `v1_ss#branch`,
  `@rm_ss[rsh]` — `v(out_ss)`, `i(v1_ss)`, `@rm_ss[rsh]` read them bare, in
  `print` and in `let`. The banner names all three forms.
- **The devices follow the `corner` variable when a loop ends.** `corners`
  and the `autocorner` pass put the variable back and then call
  `OSDImcCornerLeave`, which makes the writes the next run would have made:
  every cornered parameter back to its nominal when no corner holds, or to
  the deck's corner when one does. `showmod` after the pass shows the
  nominal; with `set corner=ss` in the deck it shows `ss`.

## Verification

| check | result |
|---|---|
| `run a16.raw` (binary; then ascii) under the option, `load`, `setplot` | three plots named `(corner tt)`, `(corner ss)`, `(corner ff)`; `v(out)[10]` 0.863, 0.798, 0.833 on tran3, tran2, tran1; `(appended)` twice; no *made no plot* |
| `tran`; `meas tran a find v(out_ss) at=200u`, `b … v(out_ff)`; `setplot tran2`; `meas tran c find v(out) at=200u`; tran3, `d` | a = c = 0.798085, b = d = 0.86326; `meas ac` and `meas dc` on their combined plots answer too |
| `.option autocorner savemc=…`; `op`; `writemc y=v(out)`; `writemc y2=v(out_ss)` | rows tt/ss/ff carry y 0.8333, 0.7981, 0.8633; no `y2` column, the hint once |
| `save all @rm[rsh]`; `op`; `print @rm_ss[rsh] i(v1_ss) v1_ss#branch`; `let z=@rm_ff[rsh]*2` | 115, −7.98e-4, −7.98e-4, z = 176 |
| `op`; `showmod rm`; `set corner=ss`; `op`; `showmod rm`; `unset corner autocorner`; `corners …`; `showmod rm` | rsh 100, 115, 100 |
| the E-661 binaries on the suite | 9 of 21 fail |

Full sweep 530 of 530 on both solvers.

## What this does not do

- The batch-mode line *incomplete or empty netlist … no simulations run!*
  after a control-script pass with a failing corner is E-438's `sim_status`
  left nonzero by that corner's run, on the old binaries too; not this.
- `.print`/`.plot` cards under `-r` are ignored, as ngspice always has.
- A combined plot older than the last pass keeps `pl_kind` for `meas`, but
  `writemc` serves the last pass's rows only, the rows the file has.
