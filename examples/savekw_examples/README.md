# Enhancement-496 — a plot keyword is not a signal name

```
python3 verify_savekw.py
```

46 checks, a few seconds. **15/46** against the pre-fix binary — **31** checks
discriminate.

## What it is

Reported from use:

```
.option saveused
pyplot v(a[0]) xlabel 'something'

  ->  Warning: save 'xlabel': nothing of that name is in this analysis,
               so no such vector is produced.
```

`xlabel` is the plot command's own grammar.

`.option saveused` ([E-469](../../enhancements_doc/Enhancement-469.md)) reads the
control block and saves what it believes is mentioned there. Its bare-word scan
took every argument that was not a number, a redirection or an expression — with
no knowledge of the commands' own keywords:

| written | collected as vector names |
|---|---|
| `plot v(a) xlabel 'x' ylabel 'y' title 'T'` | `xlabel`, `ylabel`, `title` |
| `plot v(a) vs v(b)` | `vs` |
| `meas tran m1 FIND v(b) AT 50u` | `tran`, `m1`, `find`, `at` |

**The answer was never affected** — E-469 over-collects on purpose, and a save
matching nothing produces nothing. The names were collected in silence until
[E-493](../../enhancements_doc/Enhancement-493.md) added the unmatched-save
warning, which exposed the flaw rather than causing it.

## The fix, in two parts — the second is the smaller one

1. **An inferred save is never reported.** E-493's warning exists to catch a name
   the *author* wrote and got wrong. Registration now records which is which, and
   the warning skips the ones `saveused` guessed. This covers every keyword of
   every command, present and future.
2. **The plot grammar is skipped by the scan**, and `meas` contributes no bare
   words (its vectors arrive as `v(...)`/`i(...)`, already taken by the reference
   scan). On its own this would be the [E-487](../../enhancements_doc/Enhancement-487.md)
   trap — a hand-maintained list that rots invisibly — which is why part 1 is
   what actually answers the report.

## What must not move

Nothing about *what is saved*. Every value is compared against the same run
without the option: plain plot, plot with keywords, `plot … vs …`, `meas` then
plot, `let` then plot. `all` still means everything; `wrdata`'s file name is
still not a vector; an explicit `.save` still makes `saveused` stand aside; a
node genuinely named **`title`** or **`vs`** keeps the value it has without the
option; and `.save`/`.probe` of a name that matches nothing still warns.
