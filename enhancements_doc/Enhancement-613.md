# Enhancement-613: a `savemc` file that cannot be opened is said, and its directory is made

**Scope:** `src/frontend/mcsave.c` — the first row of a circuit now makes the directories
of a given name (`mcs_mkdirs()`, each level, like `mkdir -p`), tries the open
(`mcs_can_open()`) and, when it fails, says why and falls back to the dated default
beside the netlist, or — when that fails too — says so and records nothing for the
circuit; a later open that fails (`text_rewrite()`, `xlsx_write()`) is reported once
instead of returning in silence, and the rows stay in memory for the next try.
`mcsave.h`: `MCSAVEappend()` returns `-3` for a circuit without a file, and `writemc`
says so once. `examples/savemc_examples/` grows 24 → 30 checks per solver; handbook
[§3.6](../docs/handbook/03-ngspice-workflows.md), the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §8, the
suite README. **ngspice only.** F7 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`savemc_examples`](../examples/savemc_examples/) 30 of 30 per solver, both
solvers; full sweep 505 of 505.

## What was wrong

```
.option savemc=nodir/p8a.csv
```
```
Note: savemc: recording the 1 parameter with statistics, one row per analysis run, to ./nodir/p8a.csv
```

and then nothing: no error, no file, every row and every `writemc` value of the run
lost. The recorder chose the name at the first row and printed it, but the only place
the file was opened was the writer of the row — `text_rewrite()` for csv/txt,
`xlsx_write()` for a workbook — and each of them answered a failed `fopen()` with a
bare `return`. Every later row tried again, failed again, and said nothing again. The
same silence covered a name that is a directory, a read-only tree, a directory removed
during the run, and the `myrun/` that Enhancement-612 used to fold `MyRun/` to on a
case-sensitive volume.

## What changed

The name is tried when it is chosen, at the first row, so a name that cannot be
written is found then and not never:

- **the directories of a given name are made** — each level in turn, the way `pre_osdi`
  makes its `osdi/` directory (`NG_MKDIR`, `_mkdir()` on Windows). `savemc=results/run3/draws.csv`
  in a fresh project directory creates `results/run3/` and writes there; a drive letter
  or a leading `/` is left alone, an existing level is skipped;
- **a name that still cannot be opened is reported with the reason, and the rows go to
  the dated default beside the netlist** — the reason is the directory that could not
  be made (`cannot create directory ro/sub: Permission denied`) when that is what
  failed, otherwise the open's own (`Is a directory`, `Permission denied`). The note
  that follows names the file actually used:
  ```
  Warning: savemc: cannot open ./isdir.csv (Is a directory); recording to ./mcparams_20260912_102949.csv instead
  Note: savemc: recording the 1 parameter with statistics, one row per analysis run, to ./mcparams_20260912_102949.csv
  ```
- **when the default cannot be opened either** — a read-only netlist directory — the
  recorder says so once and records nothing for that circuit; a `writemc` in that
  circuit says once that its value is not recorded, instead of nothing:
  ```
  Error: savemc: cannot open ro2/mcparams_20260912_103036.csv (Permission denied); nothing is recorded for this circuit
  writemc: savemc could not open a file for this circuit (said above), so ia is not recorded (said once)
  ```
- **a later open that fails is said once**, and the rows are kept: a directory removed
  while the file is open, a disk that fills. The rows accumulate in memory as they
  always did; the first rewrite after the directory is back (a new column, a workbook's
  periodic write) writes the file complete:
  ```
  Error: savemc: cannot write ./nodir/late.csv (No such file or directory); the rows so far are kept and written when the file can be opened again
  ```

The probe open creates the file empty; the row that follows in the same call writes
it, so nothing observable changes for a name that could always be opened — the note,
the file, its contents and its timing are as before.

## Verification

| check | result |
|---|---|
| `savemc=NewDir/Sub/Rows.csv`, no `NewDir` | both levels created; two rows with their `writemc` column; no warning |
| `savemc=NewDir/Book.xlsx`, no `NewDir` | the directory created; a valid workbook, the header and two rows |
| `savemc=IsADir.csv` where that is a directory | the warning gives the reason and the fallback; the note names the fallback; the row is there |
| a read-only netlist directory, `savemc=nodir/x.csv` (by hand) | the warning (`cannot create directory … Permission denied`), then the error, then `writemc`'s note — nothing written, nothing silent |
| the directory removed while the file is open, then restored | `cannot write … rows so far are kept` once; the file complete afterwards: four rows, `ia`/`ib`/`ic` filled where written |
| through `libngspice` (the KiCad host harness), `savemc=HostDir/Sub/host.csv` | the directories made, the row and its `writemc` value in the file |
| the 24 existing checks | unchanged |
| `savemc_examples` | 30 / 30, both solvers |
| full sweep | 505 of 505 |
