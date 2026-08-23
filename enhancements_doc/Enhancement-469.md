# Enhancement-469 — `.option saveused`

Save only the vectors the control block actually reads.

## Why

An analysis stores every node at every point unless a `save` says otherwise. On
a small circuit that costs nothing. On a large one it is the run:

| a 2448-unknown dielectric stack, 201-point parameter sweep | |
|---|---|
| no `save` | **104.73 s** — 521 ms/point |
| hand-written `save pin[2] pin[3] pout[2] pout[3]` | **7.22 s** — 35.9 ms/point |

A factor of **14.5**, from one line the author has to remember to write, and
then to keep in step with the `wrdata` beside it. Nothing warns when the two
drift apart; the deck simply gets slow again.

With the option on:

```
.option saveused        (or `set saveused` from .spiceinit)
```

| the same deck, no `save` line at all | |
|---|---|
| `.option saveused` | **7.08 s** — 35.2 ms/point |

and the written results are **byte-identical** to the hand-saved run.

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

`examples/saveused_examples/verify_saveused.py` — **23/23**, both solvers. The
observable is the set of vectors in the resulting plot, read with `display`, and
names are compared rather than counted so a check cannot pass on the right
number of the wrong vectors.

Covered: the unrestricted baseline; one vector, two vectors, a bare node name,
`print`, and `meas` contributing what it reads; the `let` dependency above; all
three stand-aside cases, with the explicit-`save` case asserted identical with
the option on and off; and all ten spellings of the option.

Full regression: see the change report. ngspice-only.
