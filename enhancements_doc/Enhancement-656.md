# Enhancement-656: `.option autocorner` — a run-class command at every declared process corner, for decks without a control script

**Scope:** `src/frontend/runcoms.c` (the hook at the top of `dosim`, the one
dispatcher of every run-class command, batch-mode `run` and the shared library's),
`src/frontend/com_sweep.c` (`autocorner_wanted`, `autocorner_run`, `ac_resample`,
`ac_new_plot`; the `sw_running_cmd` counter around a loop command's own runs),
`src/frontend/com_sweep.h`, `src/frontend/com_optimize.c` (`opt_run_cmd` brackets its
runs with the same counter), `src/frontend/typesdef.c` (the `autocorner` plot type),
`src/frontend/spiceif.c` (`autocorner`/`noautocorner` known options),
`examples/autocorner_examples/` (new, 14 checks per solver); handbook
[§3.7](../docs/handbook/03-ngspice-workflows.md). **ngspice only.** Phase 3 of the
corner design ([E-654](Enhancement-654.md) the attribute and `.option corner=`,
[E-655](Enhancement-655.md) the `corners` command).

**Suites:** [`autocorner_examples`](../examples/autocorner_examples/) 14 of 14 per
solver, both solvers (12 fail on the E-653 binaries); `cornerscmd`, `vacorner`,
`savemc`, `writemc`, `sweepanalysis`, `mcyield`, `multisave`, `osdimc`, `optimize`,
`crashfix`, `plotorder` unchanged; full sweep 529 of 529.

## What was asked

A schematic's directive text holds options and dot cards, not a control script, so
the `corners` command is out of a schematic's reach and `.option corner=ss` gives it
one corner per run. The corner analysis a schematic can ask for is an option: the
run it makes anyway, at every corner, with the results where the host reads them —
the current plot's vectors against its scale.

## What changed

**`.option autocorner`** (also `set autocorner`; `noautocorner`/`unset` turn it off).
With it set, every run-class command — `op`, `tran`, `ac`, `dc`, …, the batch-mode
`run` and the shared library's — runs at the nominal `tt` and then at every corner
the loaded Verilog-A models declare, in declaration order, exactly as
`set corner=<name>` followed by the command would (E-654 applies each corner; a
`.option savemc` file tags each row, E-655). Then:

- **The per-corner plots are kept**, each named with its corner — `Operating Point
  (corner ss)`, `Transient Analysis (corner ff)` — so `setplot` tells them apart and
  batch-mode `.print`/`.plot` cards, which serve every plot of their type
  ([E-602](Enhancement-602.md)), print each corner.
- **A combined plot is made current.** For each plot the nominal run made, an
  `autocorner<n>` plot holds the nominal's vectors under their own names and each
  other corner's under `<name>_<corner>` — `v(out_ss)`, `i(v1_ss)`, `out_ff` — on the
  nominal's scale, copied as it is (an `ac` plot's complex `frequency` included) with
  every corner's waveform resampled onto it (linear; real and imaginary parts alike;
  an identical grid is copied outright). One scale serves them all, which is what a
  host that reads the current plot draws. An `op` plot's scale is its first vector,
  so that vector gets its corner copies too; a true axis (`time`, `frequency`) does
  not. Vector types are kept, so a voltage stays a voltage.
- **The variables** `$autocorner_plot` (the combined plot), `$autocorner_plots` (the
  per-corner ones), `$autocorner_names` and `$autocorner_n` describe the run; a plain
  run afterwards clears them, so they never describe stale plots.
- **A corner whose run failed** makes no plot and is said (`autocorner: corner bad:
  the run made no plot`); the combined plot simply lacks its vectors.
- **Where it does not apply:** inside a loop command's own runs — `sweep` (its `dc`
  handover included), `montecarlo`, `corners`, `wcd`, `highsigma`, `optimize` set the
  corner or hold a trial themselves, and each brackets its runs with a counter the
  hook reads — to `resume`, and when no loaded model declares a corner (a single run,
  no banner). The `corner` variable is put back afterwards, so a deck's
  `.option corner=ff` holds and none stays none.

## Verification

| check | result |
|---|---|
| `op` under the option | the banner; `v(out)`, `v(out_ss)`, `v(out_ff)` equal three `set corner=` runs |
| the plots afterwards | `op1`–`op3` named with their corner; `$autocorner_plot`=`autocorner1`, plots, names, n |
| an op plot's first vector, branch currents | `in_ss`, `in_ff`, `v1#branch_ss` present |
| `tran` | one `time` scale, equal lengths, the corner's own plot agreeing at the end |
| `ac` | `frequency` kept complex; `vp(out_ss)`, `vm(out_ff)` equal the corner plots' |
| batch `.op` + `.print op` | three blocks, `(corner tt/ss/ff)`, rsh 100/115/88 |
| the `corner` variable | a deck's `ff` holds; none stays none |
| `corners`, `montecarlo`, `sweep`, `optimize` under the option | inert; the plain `op` after them loops once |
| a failing corner | said; no phantom `out_bad`; the others intact |
| no declared corner | a single run, no banner, no variables |
| `unset autocorner` | a single run; the stale variables cleared |
| batch `run` with `savemc` | rows tagged tt, ss, ff |
| the `run` command | loops too |
| vector types | `out_ss : voltage` |

Full sweep 529 of 529 on both solvers.

## What this does not do

- A raw file (`run <file>`, `-r`) is written by each corner's run in turn, so it
  holds the last corner; the plots hold every corner.
- The combined plot resamples onto the nominal's scale; a corner's own time points
  are in its own plot, kept.
- Batch dot cards print the corner plots newest first (the plot list's order).
- The option is per session or deck; a `.lib` corner section is not a corner it
  visits.
