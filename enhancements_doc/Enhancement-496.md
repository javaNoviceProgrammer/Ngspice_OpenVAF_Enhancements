# Enhancement-496 — a plot keyword is not a signal name

**Files:** `src/frontend/dotcards.c`, `src/frontend/breakp2.c`,
`src/frontend/outitf.c`, `src/include/ngspice/ftedebug.h`,
`src/include/ngspice/ftedefs.h`, `src/include/ngspice/fteext.h`.

**Suite:** `examples/savekw_examples/` — 46 checks.

## Why

Reported from use, not from a hunt:

```
.option saveused
...
pyplot v(a[0]) xlabel 'something'
```

```
Warning: save 'xlabel': nothing of that name is in this analysis,
         so no such vector is produced.
```

`xlabel` is the plot command's own grammar. The author never asked for a vector
of that name, and the message tells them one is missing.

## What was wrong

Enhancement-469's `.option saveused` reads the control block before it runs and
saves every vector it believes is mentioned there. Its bare-word scan took
**every** argument of an output command that was not a number, a redirection or
an expression:

```c
if (strpbrk(tok, "()[]@=*/+-,'\"")) { tfree(tok); continue; }  /* the ref scan has it */
e469_add(wl, tok);                                             /* everything else */
```

with no knowledge of those commands' own keywords. So:

| written | collected as vector names |
|---|---|
| `plot v(a) xlabel 'x' ylabel 'y' title 'T'` | `xlabel`, `ylabel`, `title` |
| `plot v(a) vs v(b)` | `vs` |
| `meas tran m1 FIND v(b) AT 50u` | `tran`, `m1`, `find`, `at` |

All 22 plot keywords, `hardcopy` likewise, and `meas` worst of all — it names its
analysis, its result and its function as bare words.

**The answer was never affected.** Enhancement-469 deliberately over-collects,
because under-saving would cost the answer, and a save matching nothing produces
nothing: the vector the author asked for comes back bit-identical with zero, one
or three stray keywords present. The names were collected in **silence** until
Enhancement-493 added the unmatched-save warning — which exposed this flaw rather
than causing it.

## The fix, in two parts

**The order of importance is the reverse of the obvious one.**

### 1. An inferred save is never reported

Enhancement-493's warning exists to catch a name the **author** wrote and got
wrong — `.save v(nosuch)`. A name `saveused` guessed on their behalf is not that.
Registration now records which it is (`db_auto` on `struct dbcomm`, carried to
`save_info.autosaved`), and the warning skips the inferred ones.

The flag is set only around `ft_saveused()`'s own `com_save()` call, so every
other route — `.save`, `save`, `.probe`, `savecurrents` — is untouched and still
reports an unmatched name exactly as before.

This covers **every keyword of every command**, including any the list below
fails to enumerate.

### 2. The grammar is skipped by the scan

The plot family (`plot`, `pyplot`, `gnuplot`, `hardcopy`) now knows its own
keywords, and `meas`/`measure` contribute no bare words at all — the vectors they
read arrive as `v(...)`/`i(...)`, which the reference scan already takes from
every line whatever command it belongs to.

This stops the pointless work, but **on its own it would be the Enhancement-487
trap**: a hand-maintained list that silently rots as keywords are added, and
whose failures are invisible. It mirrors `CT_PLOTKEYWORDS` in `cpitf.c`, which
cannot be reused because that table is built for tab completion and only in an
interactive session. A keyword missing from the copy costs nothing but the old
noise for that one word — which is exactly why part 1, not part 2, is what
answers the report.

## What must not move

Nothing about **what is saved** changes, and the suite pins that by comparing
every value against the same run *without* the option:

* a plain plot, a plot with keywords, `plot … vs …`, `meas` then plot, and
  `let r = …` then `plot r` — all identical either way;
* **`all` still means everything**; `wrdata`'s leading file name is still not a
  vector; an explicit `.save` still makes `saveused` stand aside entirely;
* **a node genuinely named `title` or `vs`** keeps the value it has without the
  option — the keyword skip cannot cost a real vector;
* `.save v(nosuch)`, `.probe v(nosuch)`, and `.save v(nosuch)` beside
  `.option saveused` all still warn.

## Verification

```
python3 examples/savekw_examples/verify_savekw.py   # 46/46
python3 examples/run_regression.py                  # 410/410
```

**15/46** against the pre-fix binary, so **31 of 46 checks discriminate**. The
other fifteen are the controls above — most importantly that a name the deck
really did write is still reported, and that `saveused` still saves what it
always saved.
