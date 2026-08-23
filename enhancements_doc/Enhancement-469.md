# Enhancement-469 — `.option saveused`

Save only the vectors the control block actually reads.

## Why

An analysis stores every node at every point unless a `save` says otherwise. On
a small circuit that costs nothing; on a large one it can be the run.

**The headline figure this shipped with has since been superseded, and the
honest account matters more than the number.** As measured on a 2448-unknown
dielectric stack over a 201-point parameter sweep, a hand-written `save` of the
four written vectors took the run from 104.73 s to 7.22 s — a factor of 14.5 —
and `.option saveused` reproduced it exactly with no `save` line at all.

**Enhancement-470 then removed the cause.** That 14.5× was not the cost of
*storing* vectors; it was the quadratic node teardown between sweep points,
which E-470 fixed properly. On the same deck today, at 1001 points:

| | time | peak RSS |
|---|---|---|
| hand-written `save` | 6.67 s | 88.4 MB |
| `.option saveused` | 6.71 s | 83.6 MB |
| no save at all | 6.72 s | 86.6 MB |

Identical at 5001 points too. **For a sweep, this option now buys nothing** —
E-470 subsumed it.

Where it still earns its keep is a **transient**, where every timepoint
accumulates into one plot rather than being torn down. A 601-node chain over
20001 timepoints:

| | peak RSS |
|---|---|
| no save | **56.6 MB** |
| hand-written `save` | 9.2 MB |
| **`.option saveused`** | **9.3 MB** |

Six times less memory, matching a hand-written save exactly, and it scales with
nodes × timepoints — on a long run that is the difference between fitting in RAM
and not. That is the benefit that survives, and the one to reach for the option
for.

```
.option saveused        (or `set saveused` from .spiceinit)
```

## What is collected

Every `v(...)`, `i(...)` and `@dev[param]` reference **anywhere in the control
block**, plus the plain node names given to an output command
(`wrdata`, `write`, `plot`, `pyplot`, `gnuplot`, `hardcopy`, `print`, `wrs2p`,
`fourier`, `four`, `fft`, `psd`, `spec`, `meas`).

That is deliberately wider than "the vectors named in the `wrdata` line", and
the reason is a correctness one. Scanning only the output command's arguments
would miss

```
let r = v(out) - v(mid)
wrdata results.txt r
```

`r` is not a node; the two vectors that build it would go unsaved and a deck
that worked before would stop working. **Under-saving turns a performance
option into a wrong answer**, so the scan errs the other way: over-saving costs
a little memory, under-saving costs the run. The suite pins this case
explicitly.

## A wildcard accessor is a knob, not a vector

The scan takes `@dev[param]` references from every line, and the commonest such
reference in a control block is a **sweep knob**:

```
sweep @*[wavelength_nm] lin 1001 1308.0 1313.0
```

`save` cannot expand a wildcard device name, so handing it one produced
*"a wildcard device name is not expanded here, so this vector will stay empty"*
— once per sweep point. The results were right; the noise was entirely this
feature's invention, and it appeared the moment a real deck dropped its `save`
line, which is exactly what the option is for.

Wildcard accessors (`@*[...]`, `@#*[...]`) are no longer collected. A **named**
accessor still is: `@r1[resistance]` is a perfectly good thing to save, whatever
command it appeared on.

## When it stands aside

The option does nothing at all — the run is exactly what it would have been —
when:

- **an explicit `save` or `.save` is present.** The author has already said what
  they want, and quietly adding to it would make their line mean something
  other than what it says. The suite checks that such a deck is bit-identical
  with the option on and off.
- **`all` is given to an output command**, which asks for everything.
- **the block contains no output command**, where there is nothing to infer
  from.

## Reading the option

Both spellings work, and every off-word is honoured:

| | |
|---|---|
| on | `.option saveused`, `=1`, `=true`, `=yes`, `=on`, `set saveused` |
| off | `.option saveused=0`, `=false`, `=no`, `=off`, `.option nosaveused` |

A deck card wins; a `set saveused` from `.spiceinit` applies only when no card
mentions it. The option cards are read in `inp.c` next to `autobus`, for the
reason recorded there: **the option variable is not published until
`inp_dodeck()` runs**, which is after this decision has to be made, so the
cards are read directly. Reading it any other way is what Enhancements 454, 462
and 464 each had to repair in this same area.

The name is registered in `spiceif.c`'s known-option list, so it does not draw
Enhancement-451's "unknown option" warning.

## Why it is not called `autosave`

That was the name asked for, and it is already taken. **Enhancement-192** owns
`autosave`: `set autosave=<file>` names a checkpoint to be written when a
transient is interrupted.

The collision was not merely cosmetic. A checkpoint filename is a *string that
is not an off-word*, so reading `autosave` as a boolean here would have switched
vector filtering on for every deck that uses E-192's checkpointing — silently
discarding nodes those decks never asked to lose. The first implementation did
exactly that, and its own suite file overwrote E-192's, which is how it came to
light: the regression suite count did not go up when a suite was added.

`saveused` is the shipped name. The suite pins that the two options are
independent: a deck carrying both `.option saveused` and
`set autosave=<file>` filters vectors and checkpoints, neither disturbing the
other.

## Where it runs

In `ft_saveused()`, called from `inp.c` immediately after `ft_dotsaves()` and
immediately before the control block executes. That ordering is the whole
design: `ft_dotsaves()` has already installed any explicit `.save`, so the
stand-aside test can see it, and no analysis has run yet, so the save list is
complete before it is needed.

## Verification

`examples/saveused_examples/verify_saveused.py` — **26/26**, both solvers. The
observable is the set of vectors in the resulting plot, read with `display`, and
names are compared rather than counted so a check cannot pass on the right
number of the wrong vectors.

Covered: the unrestricted baseline; one vector, two vectors, a bare node name,
`print`, and `meas` contributing what it reads; the `let` dependency above; all
three stand-aside cases, with the explicit-`save` case asserted identical with
the option on and off; and all ten spellings of the option.

Full regression: see the change report. ngspice-only.
