# Enhancement-612: the name of a `savemc` file keeps its case and its bytes

**Scope:** `src/frontend/inpcom.c` — the deck reader's case folding (a new branch for an
`.option` card, or the `option` command of a `.control` block or `.spiceinit`, that names
a file) and `inp_casefix()` (which `inp_getopts()` runs over every `.option` card), with
three shared helpers naming the file-valued options: `savemc=`, `automc_save=`,
`osdimc_save=` (Enhancement-610). `examples/savemc_examples/` grows 17 → 24 checks per
solver; handbook [§3.6](../docs/handbook/03-ngspice-workflows.md), the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §8, the
suite README. **ngspice only.** F6 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`savemc_examples`](../examples/savemc_examples/) 24 of 24 per solver, both
solvers; full sweep 505 of 505.

## What was wrong

`.option savemc=<name>` names a file, and the deck reader treated the name as it treats
every other word of a netlist:

- **the case was folded.** `savemc=MyRun/Draws.csv` wrote `myrun/draws.csv`. On the
  default macOS volume that is the same file; on a case-sensitive volume — Linux, or an
  APFS volume formatted that way — `myrun/` does not exist, and with the recorder's
  silence on a directory it cannot open (F7 of the same hunt, since fixed in
  [Enhancement-613](Enhancement-613.md)) every row is lost
  without a word. Under KiCad, whose netlist carries an absolute path, the note read
  `to /private/tmp/claude-501/-users-meisam-git-ngspice-openvaf-enhancements/…/host.csv`
  while the `pre_osdi` line beside it kept its case — the reader exempts `pre_osdi`,
  `osdi`, `write`, `wrdata`, `source`, `cd`, `load` and a few more from the folding,
  and `.option` was not on the list;
- **every non-ASCII byte became `_`.** `inp_getopts()` runs `inp_casefix()` over each
  `.option` card, and that function replaces a byte `isprint()` rejects — every byte of
  a UTF-8 sequence — with `_`: `Résumé_MC.csv` was written as `r__sum___mc.csv`. The
  note showed the mangled name, so it was findable, but only by reading the note;
- **a quoted name lost its quotes**, and with them the spaces it was quoted for:
  `inp_casefix()` turns `"` into a space on a card that is not `.param`, `.subckt`, a
  `.model` or an `x` line, so `savemc="dir with space/x.csv"` reached the lexer as three
  words.

## What changed

The value of a file-name option is data and is left alone by both passes. Three small
helpers carry the knowledge once: the table of option names, a test for "this position
starts one of them" (the name has to begin a word — `nosavemc=` is not `savemc=`), and
the end of the value (past the closing quote of a quoted one, otherwise the first white
space).

- **The reader** folds an `.option` card that names a file through
  `keep_case_of_file_options()`: the option's name and every other word on the card are
  lower-cased as before (`OSDIMC MCSEED=5` on the same card is still recognised and
  honoured), the value keeps its bytes. The `option` command of a `.control` block or a
  `.spiceinit` goes through the same branch.
- **`inp_casefix()`** skips the value whole on an `.opt` card: no quote removal, no `_`,
  no folding. `listing` shows the card as written.
- A **quoted** value keeps its quotes through both passes, so the lexer keeps it as one
  word and `cp_unquote()` strips them: `savemc="dir with space/My Draws.csv"` is a path
  with spaces. A format keyword is still matched case-insensitively (`savemc=CSV`), and
  so is an extension (`automc_save=Osdi.TXT` picks the tab-separated writer).

```
.option savemc=MixedCase/Draws.csv OSDIMC MCSEED=5
```
```
Note: savemc: recording the 2 parameters with statistics, one row per analysis run, to ./MixedCase/Draws.csv
     3 : .option savemc=MixedCase/Draws.csv osdimc mcseed=5
```

Nothing else on an `.option` card changes: the three names are the only ones whose
value is a path, and every other word of the card is folded exactly as before.

## Verification

| check | result |
|---|---|
| `savemc=MixedCase/Draws.csv` | the file has exactly that name; the note and `listing` show it |
| `OSDIMC MCSEED=5` on the same card | folded and honoured: the baseline row is nominal, trial 2 drew |
| `savemc="dir with space/My Draws.csv"` | one file at that path, its rows complete |
| `savemc=Résumé_MC.csv` | the bytes kept; the note names the file as written |
| `automc_save=MixedCase/Osdi.TXT` | the name kept, the `.TXT` extension picks the tab-separated writer |
| `option savemc=MixedCase/FromControl.csv` in a `.control` block | the name kept |
| `savemc=CSV` | still the format keyword: a dated `mcparams_` file, no file named `CSV` |
| the 17 existing checks | unchanged |
| `savemc_examples` | 24 / 24, both solvers |
| full sweep | 505 of 505 |
