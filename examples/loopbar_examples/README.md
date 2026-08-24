# Enhancement-477 — a progress line for the loop commands

```
python3 verify_loopbar.py
```

18 checks, one solver (this is a front-end output feature; the bar bytes do not
depend on the linear solver, and `[16]` pins that the numbers do not change).

## The problem

`sweep`, `montecarlo`, `highsigma` and `wcd` all run N analyses in a loop, and
all four set `ft_optimizing` to silence per-point chatter (Enhancement-130). So
they printed their banner and then **nothing at all** — a forty-point sweep of a
slow transient looked hung for minutes.

## Why the inner analysis's bar is not the answer

ngspice already draws a bar for `tran` / `ac` / `dc` / `noise`. Reusing it here
fails three ways:

- it measures the wrong thing — it runs 0 → 100% for *every* point, so on a
  40-point sweep it resets forty times and never says how far the sweep is;
- it redraws the same terminal line with `\r`, so an outer bar and the inner bar
  would overwrite each other;
- the loop commands had already decided against it, which is what `ft_optimizing`
  is doing in `com_sweep.c`.

But the inner number is not worthless: with three points and a one-minute
transient each, an outer-only bar sits at `1/3` and looks frozen. So **one line
carries both**, and the inner fraction also advances the outer bar within the
point so it moves smoothly rather than stepping once per analysis:

```
 sweep: point  7/40  [=========               ]  17%   (tran 63%)
```

## Two drivers, and why neither alone is enough

| driver | covers | fails alone |
|---|---|---|
| `outitf.c`, off the analysis's data path | intra-point refresh | the default analysis is `op`, which produces no swept data points and never reaches it |
| the loop command, at each point boundary | many fast points, any analysis | while a point runs the command is blocked inside the analysis and cannot refresh anything |

Checks `[5]` and `[8]` pin one each — `[5]` requires the percentage to advance
*within* point 1, `[8]` uses a plain `op` sweep where only the boundary driver
can fire.

## wcd is indeterminate

`wcd` iterates a Hasofer-Lind search to convergence, usually well before
`maxiter`, so a bar drawn against `maxiter` would sit low and then jump to done.
It gets a counter and no percentage (`[11]`), which also pins that the counter is
drawn *before* the result rather than after it — the first version released the
line at the `ft_optimizing` restore, which for `wcd` runs at the end of the
function, so the last frame landed underneath the answer.

## The switch

Auto by default: drawn only when stdout is a terminal, because the line is
redrawn with `\r` and a redirected run would otherwise collect one enormous line
of bar frames. `set loopbar` forces it on (that is how this suite tests it),
`set loopbar=0` / `false` / `no` / `off` and `set noloopbar` force it off, and
`set noloopbar=0` returns to auto. `[12]` tests all eight spellings, because
Enhancements 450, 451, 454, 466 and 467 each shipped an option here where a
spelling meaning *off* turned the feature **on**.

`[17]` and `[18]` allocate a real pty, because auto-on-a-terminal is the default
path and cannot be observed from captured output — without a pty the two look
identical to "forced off".

`set norefvalue` mutes it too (`[13]`), the same variable that mutes the analysis
bar. Note the spelling: the frontend variable is `norefvalue`, the C flag it sets
is `ft_norefprint`, and using the flag's name in a deck silently does nothing.

## What must not change

- a plain `tran` still shows its own bar (`[14]`) — the new branch in
  `outp_print_reference()` is entered only while a loop command is active;
- `optimize` stays completely silent (`[15]`) — Enhancement-130's behaviour;
- the swept numbers are byte-identical with the bar on and off (`[16]`).

## Harness note

`[14]` first failed because the test's transient was too short to cross the
0.25 s throttle: a fast run legitimately draws nothing. A progress-bar check must
size its deck to the throttle, not assume a bar exists.

## Watching it in practice: `set noinit`

A `tran` prints its **"Initial Transient Solution"** table once *per point*, and
that scrolls the redrawn line out of view — so a `tran` sweep shows the line
briefly and then a wall of node tables. That printout predates this enhancement
and other things read it, so it is not suppressed here; but ngspice already has
the lever:

```
set loopbar
set noinit
sweep @r1[resistance] lin 40 500 4k -analysis "tran 10u 1m" -output v(b)
```

`[19]` pins it (3 tables without, 0 with), so this advice stays true.

That check first passed **vacuously**: the suite's own `run()` sets
`option noacct`, and the table is gated on `!ft_noacctprint && !ft_noinitprint`,
so both sides read zero tables. It now builds its deck without `option noacct`
and asserts the *3 vs 0* difference — a "pass" where both sides are empty proves
nothing.

## The first frame, and two ways a check can be blind

The frame for point 1 is deliberately **not** drawn. A frame ends with `\r` and
fills the line to a constant width, so the solver announcement — printed by the
first analysis and shorter than a frame — overwrote only its leading columns and
left the rest as a tail:

```
Using SPARSE 1.3 as Direct Linear Solver          ]   0%
```

`[20]` pins the whole class rather than that one banner: for each physical line
it asks what a terminal would actually show, and bar residue may appear only on a
bar line. Getting that check to *fail* on the broken build took two attempts:

- the residue **does not exist in the byte stream** — the text after the last
  `\r` is just the banner. `\r` means "cursor to column 0", so the check has to
  composite the line the way a terminal does;
- and `subprocess(text=True)` applies **universal newline translation**, turning
  every `\r` into `\n` before the check can see it. It reads raw bytes instead.

Both earlier versions passed against the build that had the bug. A check that
cannot be made to fail on the defect it targets is not evidence of anything.

