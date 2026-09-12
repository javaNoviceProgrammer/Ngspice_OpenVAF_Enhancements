# Enhancement-615: a second deck naming the same `savemc` file gets the next free name

**Scope:** `src/frontend/mcsave.c` — a session registry of the file names the recorder
has written, each with the title of the deck that wrote it (`mcs_used_by()`,
`mcs_note_used()`, `mcs_unused_variant()`); the first row of a circuit whose given name
another deck wrote in this session takes `<stem>_2.<ext>` (the first variant this
session has not written) and says so; the registry is freed at exit.
`examples/savemc_examples/` grows 30 → 33 checks per solver; the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §8, the
suite README. **ngspice only.** F17 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`savemc_examples`](../examples/savemc_examples/) 33 of 33 per solver, both
solvers; full sweep 505 of 505.

## What was wrong

```spice
.control
source a.cir          ; .option savemc=shared.csv -- two rows
source b.cir          ; .option savemc=shared.csv -- one row
source a.cir
.endc
```
```
Note: savemc: recording the 1 parameter with statistics, one row per analysis run, to ./shared.csv
Note: savemc: recording the 1 parameter with statistics, one row per analysis run, to ./shared.csv
Note: savemc: recording the 1 parameter with statistics, one row per analysis run, to ./shared.csv
```

and one file at the end, holding the last deck's two rows. Enhancement-610's contract is
"one file per circuit: a `reset` continues it, a different deck starts its own" — and
with a fixed name "starts its own" was an overwrite: the second deck's first row opened
`shared.csv` for writing and the first deck's rows were gone, the note reading exactly
as it had for the first.

## What changed

The recorder remembers, for the session, every file name it has written and the title
of the deck that wrote it. A deck whose given name is on that list — a **different**
deck; the same deck re-sourced continues its file as before — takes the next free
variant, `<stem>_2.<ext>`, `_3`, …, the first this session has not written, and says
whose rows the original holds:

```
Note: savemc: recording the 1 parameter with statistics, one row per analysis run, to ./shared.csv
Note: savemc: ./shared.csv holds the rows of '* deck a' from earlier in this session and is kept; this deck's rows go to ./shared_2.csv
Note: savemc: recording the 1 parameter with statistics, one row per analysis run, to ./shared_2.csv
Note: savemc: ./shared.csv holds the rows of '* deck a' from earlier in this session and is kept; this deck's rows go to ./shared_3.csv
Note: savemc: recording the 1 parameter with statistics, one row per analysis run, to ./shared_3.csv
```

The variant goes through Enhancement-613's directory creation and open check like any
given name; the dated default (`savemc`, `savemc=csv`) is unique by construction and
needs none of this. A name from an **earlier ngspice run** is not protected: a fixed
name means the same file on every run, as for any output file (`write out.raw`), so a
script that runs a deck and reads its `savemc` file finds it where it always has.

## Verification

| check | result |
|---|---|
| deck A (`Shared.csv`, two rows), deck B (`Shared.csv`), deck A again, in one session | `Shared.csv` keeps A's two rows; B's row in `Shared_2.csv`; A's second run in `Shared_3.csv`; each variant announced with the first deck's title |
| a separate ngspice run with the same fixed name | replaces the file, one row, no note |
| the 30 existing checks | unchanged |
| `savemc_examples` | 33 / 33, both solvers |
| full sweep | 505 of 505 |
