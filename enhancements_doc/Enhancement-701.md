# Enhancement-701: `.option savecorner` — every corner run of a Verilog-A circuit, one row per corner, beside the netlist: the corner's name, the value in force of every cornered parameter, and what the run computed

**Scope:** `src/frontend/cornersave.c` and `cornersave.h` (new: the recorder),
`src/frontend/mcsave.c` and `mcsave.h` (the format parsing, file naming,
directory making, used-name registry, csv/txt cell writers and the workbook
writer with its font options exported for both recorders; `writemc` feeds
both), `src/osdi/osdisetup.c` and `src/include/ngspice/osdiitf.h`
(`OSDImcCornerSnapshot`, `OSDImcHasCorners`; the snapshot item's `has_stats`
and `held`), `src/frontend/spiceif.c` (the row after each run-class command;
the seven option names known), `src/frontend/com_sweep.c` (the `corners`
command's outputs and its `-mc` summary rows), `src/frontend/runcoms2.c`,
`src/main.c` (the file completed), `src/frontend/inpcom.c` (a file name keeps
its bytes), `src/frontend/Makefile.am`, `examples/savecorner_examples/` (new,
29 checks per solver); handbook [§3.7](../docs/handbook/03-ngspice-workflows.md).
**ngspice only.** Requested by the user.

**Suites:** [`savecorner_examples`](../examples/savecorner_examples/) 29 of 29
per solver, both solvers (1 of 29 on the E-699 binaries, which know no
such option); `savemc`, `writemc`, `cornerscmd`, `autocorner`, `vacorner`,
`osdimc`, `mcrecord`, `mcyield`, `mcpolicy`, `mcarming`, `mcfastpath`,
`mctrack`, `hunt3diag`, `lhs`, `sweepparam` and `wcd` both solvers, unchanged;
full sweep 532 of 532, run alone.

## What was asked

Corner analysis from Verilog-A devices — a model's `(* corner="ss=115, ff=-10%" *)`
attributes ([E-654](Enhancement-654.md)), the `corners` command
([E-655](Enhancement-655.md)) and `.option autocorner`
([E-656](Enhancement-656.md)) — produced per-corner plots and tables but no
record of the runs the way `.option savemc` ([E-610](Enhancement-610.md))
records every Monte Carlo trial. The user asked for the same recorder keyed by
corner: instead of a `trial` column, a `corner` column with the corner's name,
then the columns for all the parameters and the output calculations of that
corner run, in csv, Excel and the other formats, to go with `autocorner`.

## What changed

**`.option savecorner[=csv|txt|excel|<name>.<ext>]`** records, for every
corner run, one row of `corner`, `analysis`, `status` (`ok`, `failed`, or
`paused` for a run stopped at a breakpoint, the `resume` that ends it setting
the outcome), then:

- **every cornered parameter** — each parameter of a loaded model that
  carries a `corner` attribute, once — read off the devices when the row is
  made, as `@<model>[<param>]` for a model parameter and `@<instance>[<param>]`
  for an instance one: the corner's value under a corner, the nominal at `tt`
  (a new OSDI walker, `OSDImcCornerSnapshot`, beside the statistical
  `OSDImcSnapshot`);
- **what the run computed**: the `corners -output` values on each corner's
  row; `writemc`'s values (on an `autocorner` combined plot each value is
  evaluated on every corner's own plot and put on that corner's row, the
  [E-666](Enhancement-666.md) rule; on a plain run onto its row); and under
  `corners -mc N` the montecarlo's `yield`, `npass`, `nsamples` and `nfailed`.

**Which runs are corner runs.** Every run-class command (`op`, `tran`, `run`,
… — what `if_run` dispatches) that is not a loop command's sample: a plain run
at the deck's `.option corner=<name>` (or at `tt` without one), each corner of
an `.option autocorner` pass (`op` gives `tt`, `ss`, `ff`; a batch deck's
`run` is one run per corner), each corner of the `corners` command. Inside
`montecarlo`, `sweep`, `optimize`, `wcd` and `highsigma` the runs are the
loop's samples and make no rows — savemc records those — and `corners -mc N`
holds the recorder around its montecarlo per corner (a nested loop keeps the
outer `corners` label, E-478) and adds one summary row per corner instead,
where a parameter with statistics the corner does not hold is left empty:
the row stands for the whole sample, not for the last draw. A `dc` that
sweeps a cornered parameter itself leaves that cell empty too, as savemc's
[E-626](Enhancement-626.md) does.

**The file** is `corners_<date>_<time>.<ext>` in the netlist's directory,
unique within a second, or the name the option gives — its directories are
made, its case and bytes kept, a name another deck wrote in this session gets
`_2`, a name that cannot be opened is said with the reason and the dated
default used, exactly as savemc does, because it is the same code: the format
parsing, the naming, the directory making, the used-name registry and the
csv/txt cell writers of `mcsave.c` are exported now, and the workbook writer
became `MCSAVExlsxWrite`, a generic one-sheet writer both recorders hand their
table to (savemc's sheet is still `mcparams`, savecorner's is `corners`). The
Excel header sets a model parameter's name in bold, an instance parameter's
regular and an output's blue; `savecorner_font`, `savecorner_fontsize`,
`savecorner_model`, `savecorner_instance` and `savecorner_output` set them,
each falling back to the savemc option, so one set of font options styles
both files. csv and txt are appended row by row and flushed; a value written
after the run rewrites the last line in place, a new column the file. One
file per circuit: a `reset` continues it, a different deck starts its own,
`nosavecorner` last turns it off, and a circuit no loaded model of which
declares a corner has nothing to record, said once. None of the seven names
draws an "unknown option" warning, and `savecorner=` / `savecorner_font=`
keep their bytes through the deck's case folding.

`writemc` now serves both recorders: with savemc off and savecorner on it
puts the value on the savecorner row (it used to answer "nothing is recorded");
`writemc corner=…`, `analysis=…` and `status=…` are refused for the savecorner
row by name, as savemc refuses its fixed columns.

## Verification

| check (`examples/savecorner_examples/`) | result |
|---|---|
| `corners -output v(out) gain=v(out)/v(in)` | header `corner,analysis,status,@rm[rsh],@rm[k],@rm[vth],v(out),gain`; rows `tt` 100/2/0.45, `ss` 115/2.2/0.51, `ff` 88/1.8/0.39, outputs 0.5 |
| `corners -mc 5 -analysis op -spec v(out) -max 0.6` under osdimc | three rows, `yield` 1, `npass` 5, `nsamples` 5, `nfailed` 0; `@rm[vth]` empty at `tt`, 0.51 / 0.39 under `ss` / `ff`; without osdimc 0.45 at `tt` |
| `.option autocorner` + `op` + `writemc vout=v(out) g=v(out)/v(in)` | rows `tt`, `ss`, `ff` with `vout` and `g` on each; a batch `.op`/`.tran` deck gives three `run` rows |
| `.option corner=ss` + `op`, `unset corner` + `op`, `reset` + `set corner=ff` + `op` | rows `ss`, `tt`, `ff` in one file; the note once |
| `savecorner=txt`, `=excel`, `=Runs/Deep/Corners.csv` | tab-separated; a zip with sheet `corners`, bold model headers, blue outputs, Calibri 11; the directories made |
| `nosavecorner` last; the seven names | off; no "unknown option" |
| a model without corners | the note once, no file |
| `corners -list ss,bad` (corner `bad` moves `g` out of its range) | `ss` ok 0.5, `bad` failed with an empty output |
| `montecarlo 3`, `sweep @rm[rsh] 90 110 10`, then `op` | no sample rows; the sweep's fast path one `dc` row with the swept cell empty; then `tt` |
| savemc and savecorner together | two files, savemc's keyed by trial with its `corner` column |
| `savecorner_font=Arial savecorner_fontsize=9 savecorner_model=italic+red savecorner_output=green`; `savemc_font=Verdana savemc_writemc=navy` | the workbook's fonts; the savemc fallback |

## What this does not do

It records the cornered parameters, not every parameter of the model: the
columns are the ones a corner can move. A `.meas` card's results are not put
on the rows (a `writemc` after the run is the route, as for savemc). A
`montecarlo` alone, a `sweep`, an `optimize` or a `wcd` make no rows — those
are samples, savemc's business — and a `corners` loop nested inside a
`montecarlo` sample records its corner runs per sample, since the inner loop's
label is the one in force there. The shared library was not rebuilt (the
user's rule since E-699).
