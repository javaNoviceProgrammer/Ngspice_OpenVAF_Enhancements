# Enhancement-477 — a progress line for the loop commands

`sweep`, `montecarlo`, `highsigma` and `wcd` each run N analyses in a loop. All
four set `ft_optimizing` to silence per-point chatter (Enhancement-130), so they
printed a banner and then nothing at all until they finished. A forty-point
sweep of a slow transient looked hung.

They now draw one line, redrawn in place:

```
 sweep: point  7/40  [=========               ]  17%   (tran 63%)
```

## Why not simply keep the inner analysis's bar

ngspice already draws a progress bar for `tran`, `ac`, `dc` and `noise`, on the
"Reference value" line. Letting it through during a loop is the obvious idea and
it is the wrong one:

- **It measures the wrong quantity.** It runs 0 → 100% for *each* point. On a
  forty-point sweep it resets forty times and never answers the only question
  being asked, which is how far the *sweep* has got.
- **It fights for the same line.** Both are redrawn with `\r`; an outer bar and
  the inner bar would overwrite each other.
- **The loop commands had already ruled against it.** `ft_optimizing` is set in
  `com_sweep.c` with the comment *"silence per-point chatter"*, and
  `outp_print_reference()` returns early on that flag. That is exactly why a
  sweep was silent.

The inner number is still worth having, though: with three points and a
one-minute transient each, an outer-only bar sits at `1/3` for a minute and
reads as frozen. So the inner fraction is carried on the same line as a
secondary field, and it also advances the *outer* bar within the point, so the
bar moves smoothly instead of stepping once per analysis. Across a point
boundary the outer percentage is continuous: point 1 ends near 32% on a 3-point
sweep and point 2 begins at 34%.

## Two drivers, because neither covers both regimes

While a point is running, the loop command is blocked inside the analysis and
cannot refresh anything. Only `outitf.c`, called from the analysis's own data
path, can — so that is where the intra-point refresh comes from.

But the **default** analysis is `op`, which produces no swept data points and
never reaches that path at all. So the loop command also draws at each point
boundary.

| | few slow points | many fast points | `-analysis op` |
|---|---|---|---|
| `outitf.c` data path | yes | yes | **no** |
| point boundary | too coarse alone | yes | yes |

Both are needed. The suite pins them separately: one check requires the
percentage to advance *within* the first point, another uses a plain `op` sweep
where only the boundary driver can fire.

Both draws are throttled to 0.25 s, the same window the analysis bar uses — a
sweep may run up to `SW_MAXPTS` points, and one write per point would cost more
than the solve on a fast deck. A 4000-point `op` sweep that finishes in 69 ms
therefore draws twice, which is correct.

## `wcd` is indeterminate

`wcd` iterates a Hasofer-Lind search until it converges, usually well before
`maxiter`. A bar drawn against `maxiter` would sit low and then jump to done, so
`wcd` gets a counter and no percentage:

```
 wcd: iteration 4
```

Its line is released immediately after the loop rather than at the
`ft_optimizing` restore. The first version used the restore, which for `wcd`
runs at the end of the function — so the loop's last frame printed *underneath*
the worst-case distance it was supposed to precede.

## The first point's frame is not drawn

A frame ends with `\r`, leaving the cursor at column 0 of a line it has filled to
a constant width. Anything printed before the next redraw therefore overwrites
only its *leading* columns, and the rest of the frame survives as a tail. The
first analysis of a run prints the solver announcement, which is shorter than a
frame:

```
Using SPARSE 1.3 as Direct Linear Solver          ]   0%
```

Every later point is safe, because its frame is drawn *after* the preceding
analysis has finished printing — only the first has nothing in front of it. So
it waits: the bar appears from the first intra-point refresh, or at the second
point's boundary, both of which follow that output.

The line is also padded **and** truncated to one constant width. Padding stops
`\r` leaving stale characters from a longer previous frame; truncating stops the
line exceeding the width, because a wrapped line puts the cursor on the second
row and `\r` would then redraw only that row, leaving the first stuck on screen.

## The switch

Auto by default: drawn only when stdout is a terminal. The line is redrawn with
`\r`, and a redirected run would otherwise collect one enormous line of bar
frames in the file. (The existing per-analysis bar does not make that
distinction — capturing a plain `tran` to a file yields a screenful of
"Reference value" frames — but repeating that in new output is not an
improvement, and the regression suites capture stdout.)

| | |
|---|---|
| `set loopbar`, `loopbar=1` | forced on |
| `loopbar=0` / `false` / `no` / `off`, `set noloopbar` | forced off |
| `noloopbar=0` | back to auto |
| unset | auto |

All eight spellings are tested, because Enhancements 450, 451, 454, 466 and 467
each shipped an option in this area where a spelling meaning *off* turned the
feature **on**. `set norefvalue` mutes it as well, the same variable that mutes
the analysis bar.

Auto-on-a-terminal is the default path and cannot be observed from captured
output, so two checks allocate a real pty; without one, "auto" and "forced off"
are indistinguishable.

## Watching it in practice

A `tran` prints its "Initial Transient Solution" table once *per point*, which
scrolls the redrawn line out of view. That printout predates this work and other
things read it, so it is not suppressed here — but `set noinit` removes it and
leaves the line clean, and a check pins that (3 tables without, 0 with).

## What this deliberately does not change

- A standalone `tran` / `ac` / `dc` / `noise` still shows its own bar exactly as
  before — the new branch is entered only while a loop command is active, and
  `progressbar_examples` still passes 22/22.
- `optimize` stays completely silent. Enhancement-130 made it so, and a
  17-evaluation optimize run emits nothing.
- The numbers are untouched: a sweep's output is byte-identical with the bar on
  and off.

`outp_bar_shown` is deliberately left alone by the new branch, so
`outp_finish_reference()` stays a no-op during a loop and cannot stamp a stray
100% "Reference value" line over the loop line at the end of every point.

## Verification

`examples/loopbar_examples/verify_loopbar.py` — **18/18**. Against the shipped
pre-fix binary the same suite scores **5/18**, and the five that pass are exactly
the "must not change" checks.

Full regression, both solvers. ngspice-only.
