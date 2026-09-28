# Enhancement-753: `help all` lists every command, one line each — the listing stopped at the first command without a handler, so the eleven control keywords and the seventeen commands after them in the table were never shown, and a handful of help texts broke the one-line form (an embedded newline in `setscale`, a trailing newline in `deftype`, missing separators, periods and stray spaces)

**Scope:** a glitch report on `help all`, with a screenshot of `setscale`'s
text broken over two lines. Three files: `frontend/com_help.c` and
`frontend/com_ahelp.c` (the loops that collect the commands for `help all`
and `newhelp`) and `frontend/commands.c` (help texts in both command tables).
Nothing a command does changes; only what `help` prints.

**Suites:** `helpcmd` 18 of 18 (was 4; 9 of 18 on the E-752 binary: E-174's
four and five of the new ones), `cornerscmd`, `exitcmd` and `lrmosdi` (the
other suites that read help output) unchanged; the full sweep 533 of 533.

## What was wrong

**The visible glitch.** `setscale`'s help was two C literals joined by an
embedded newline and a two-space indent, so `help all` printed

```
setscale [vecname [vecname]] : Change default scale of current working plot
  or set/clear the scale for a single vector.
setseed [seed value] : Reset the random number generator with new seed value.
```

Reading the whole listing found the same kind of slip elsewhere: `deftype`
ended its text with a newline, which left a blank line in the middle of the
list; `remzerovec` and `sysinfo` had no ` : ` separator; `where` had no final
period.

**The invisible one.** `help all` printed 137 commands where the table has
165 for this build. `com_help` counted the table with

```
for (numcoms = 0; cp_coms[numcoms].co_func != NULL; numcoms++)
```

which stops at the first entry without a **handler**, not at the table's
terminator, the entry without a **name**. The control keywords `while`,
`repeat`, `dowhile`, `foreach`, `if`, `else`, `end`, `break`, `continue`,
`label` and `goto` have no handler (the control parser runs them), and
`while` is the first of them, so everything from there to the end of the
table was never listed: the eleven keywords and `cdump`, `mdump`, `mrdump`,
`settype`, `strcmp`, `strstr`, `strslice`, `fopen`, `fread`, `fclose`,
`linearize`, `cutout`, `devhelp`, `inventory`, `optran`, `wrnodev` and
`check_ifparm`. `help <name>` walks the table by name and always found them,
so each was reachable if you already knew it existed. `newhelp`
(`com_ahelp`) had the identical loop. This is upstream ngspice's code.

Those 28 entries carried slips of their own that nobody had seen:
`linearize` and `cutout` began with a space, `mdump` and `mrdump` wrote
`outfile:` without the separator's space, `strslice`, `fopen`, `fread`,
`fclose`, `inventory` and `check_ifparm` had no final period, `optran` and
`wrnodev` ended with a space instead of one.

## What changed

- Both loops run to the table's terminator (`co_comname != NULL`); the
  `newhelp` one is also bounded by its 512-entry array. Entries without a
  handler are listed like any other; the existing filters (a spice-only
  command under nutmeg, an entry without help text) still apply.
- Every help text in both tables (the spice table and the nutmeg one) has
  the one-line form `name args : text.`: `setscale` joined with a comma,
  `deftype`'s newline dropped, the separator added to `remzerovec` and
  `sysinfo` (`: Remove zero-length vectors.`, `: Print out system info
  summary.`), `mdump` and `mrdump` spelled `[outfile] : ...` (their argument
  is optional), the leading and trailing spaces removed, the final periods
  added, and `devhelp`'s text capitalised like the others.

`help all` now lists 165 commands, sorted, one line each, followed by the
manual links whose indented URL lines are deliberate.

## Verification

`examples/helpcmd_examples/verify_helpcmd.py` gains sections [5] to [8],
fourteen checks run in batch mode beside E-174's four interactive ones:

- **[5]** every line of the list has the form `name args : text.`: no
  continuation line, no blank line inside the list, the separator, a final
  period, one space after the name, no trailing space; the list is sorted.
- **[6]** completeness: the listed names are exactly the names in
  `commands.c`'s table that `help <name>` answers in this build (165), the
  28 from `while` down are among them, and the eleven control keywords each
  have their line.
- **[7]** `help setscale` is one line; `help` alone still prints its short
  pointer, an unknown name still gets *Sorry, no help for nosuchcmd.*, and the
  manual links still follow the list.
- **[8]** `newhelp` at the advanced level lists the keywords and the
  commands after them.

On the E-752 binary 9 of 18 pass: E-174's four, the sort order, the spacing
check (vacuously: the entries with stray spaces were not listed), and the
three single-command answers.

## What this does not do

- The help texts' wording is otherwise untouched; `optran`'s and
  `wrnodev`'s arguments are still not spelled out, and the interactive
  `help` browser (`com_ghelp` with a help directory) is not involved.
- The `help all` list still mixes the control keywords with the commands;
  it does not group them.
- The nutmeg table is fixed in the same way, but nutmeg is not built here,
  so it is not exercised.
