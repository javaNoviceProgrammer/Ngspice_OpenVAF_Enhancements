# Enhancement-499 — loop-command arguments, verdicts, and a KLU refactor kind

```
python3 verify_loopguard.py
```

49 checks, both linear solvers. 31 of them fail without the fix (36 under KLU).

## What was wrong

Round 58 probed the `sweep`/`optimize` fast path again, after
[Enhancement-498](../../enhancements_doc/Enhancement-498.md) fixed the transient
side. The reuse arithmetic was clean this time. What was wrong was everything
around it — and, underneath, one genuine memory bug that setup reuse made
reachable.

### 1. A complex refactor of a real factorisation

`klu_z_refactor` refills an existing factorisation in place, walking the L and U
index arrays that `klu_z_factor` built. Handed a **real** `Numeric` object it
walks half-sized arrays with complex strides: it reads and writes past their
ends, and a later `klu_free_numeric` frees whatever it scribbled. The malloc
abort names object `0x3ff0000000000000` — the IEEE-754 bit pattern of the double
**1.0**, a matrix *value* being freed as a pointer.

The mismatch is reachable because a `Numeric` outlives the analysis that built
it. Every AC/SP/NOISE run is preceded by a real operating point, and E-471's
setup reuse keeps the matrix standing between sweep points instead of rebuilding
it — so the second and later points arrived with the operating point's real
factorisation.

| under `.option klu` | before | after |
|---|---|---|
| `sweep -analysis ac` | `0.0` at every reused point | matches a standalone run |
| `sweep -analysis noise` | `0.0` at every reused point | matches |
| `sweep -analysis sp` | **SIGSEGV on 9 of 10 runs** | clean |
| `optimize -analysis ac` | fitted `1000`, said *converged* | fitted `10000`, as everything else does |

SPARSE was never affected, and neither was any analysis that stays real —
`op`, `dc`, `tran`, `tf`, `pz` and `disto` were all correct throughout. Both
refactor directions are now guarded: the matrix records which kind of
factorisation its `Numeric` holds, and a kind change forces a full factorisation
instead.

### 2. `optimize` parsed four of its own arguments with a weaker parser

`com_optimize.c` has always had `optnum()` — `ft_numparse`, so it understands
SPICE suffixes *and* scientific notation — and uses it for the bounds, `-target`
and `-spec`. Its integer options did not: `-maxiter`, `-samples` and
`-swarmsize` called `atoi()` and `-tol` called `atof()`, which stop at the first
character they cannot use and return 0 for text.

So `1k` meant 1000 in a bound and **1** in `-maxiter`, on the same command line:

| | evaluations | fitted R1 |
|---|---|---|
| `-maxiter 1000` | 63 | **1500.000** |
| `-maxiter 1k` (before) | 5 | 1495.000 |
| `-maxiter 2e2` (before) | 7 | 1495.000 |

`-samples 2e2` ran **2** Monte-Carlo samples while design centering still printed
a yield and a Wilson confidence interval from them. `abc` was 0 everywhere, in
silence. `sweep lin 2e2` (200 points) and `montecarlo 2e2` (200 samples) were
already right — optimize was the odd one of the three loop commands.

`-seed` had the matching hole. [E-497](../../enhancements_doc/Enhancement-497.md)
taught the `setseed` **command** to refuse `3.7`; the **option** spelling
truncated it without a word, and `-seed 0` / `-seed -3` left the run unseeded and
**not reproducible** while the author had asked in writing for a fixed seed.

### 3. "converged" when nothing was optimised

The word describes the search stopping, not the answer being the one the author
wanted. It was printed when the objective never moved at all — a parameter
outside the signal path, or a name that does not resolve, hands the **starting
value** back after three evaluations — and when the answer sat on a search bound,
meaning the optimum lies outside the range given. `-target x 0.4 0`, whose zero
weight makes the residual identically `0`, printed the most convincing number the
command can produce for a fit that never happened.

Both are visible where the verdict is printed and neither was said. This is the
duty [E-438](../../enhancements_doc/Enhancement-438.md) already discharges for
failed evaluations, and that QPSS-HB discharges when it prints *"STALLED above
tol — accepted"*.

### 4. The same shape in `sweep`'s knob

`sw_kind()` falls through to `SW_ALTER` for any name it does not recognise; the
comment on that fallback already describes what follows — `alter` reports "no
such device", the sweep runs anyway over a knob that never moves, and the user
gets a full set of points, `rc = 0`, and a plottable **flat curve whose x-axis is
named after the typo**. [E-435](../../enhancements_doc/Enhancement-435.md)
removed that shape for a subcircuit-local model name and
[E-488](../../enhancements_doc/Enhancement-488.md) for `temp`; this removes it
for every remaining spelling, exactly as
[E-431](../../enhancements_doc/Enhancement-431.md) did for an unresolved
`-output` — *"a typo, not data"*.

A malformed `list` value did the same on a smaller scale: `list 1k inf 2k 3k` ran
**one** point and called `inf`, `2k` **and** `3k` unrecognised, though
`list 1k 2k 3k` proves the last two are read without complaint.

### 5. `-overlay` threw away the timepoints the solver chose

It resampled onto a **uniform** grid of the same point count as the longest run
(`xmin + (xmax-xmin)*jj/(ncommon-1)`). A transient chooses its timepoints
adaptively — it puts them where the waveform moves — so keeping the count and
discarding the placement is exactly backwards. The overlay of an RC driven by a
0.2 µs pulse reported a peak of `0.244` where every one of its own runs, and a
standalone run, said `0.402`: **39 % low**, from the same 121 points.

It now resamples onto the **union** of the runs' own timepoints, so no run's
extremum can fall between grid points, and says which grid it used. The union is
bounded to a small multiple of the old size; past that the uniform grid is used
as before and the message says so.

Its vector names were also formatted with `%g` — six significant digits — so
`list 1000.0001 1000.0002 1000.0003` produced **three vectors all called
`vn_1000`**, of which only one could be printed or plotted. They now carry the
shortest text that reads back as the exact value, the same answer
[E-494](../../enhancements_doc/Enhancement-494.md) settled on.

### 6. Two warnings that contradicted each other

A sweep point whose analysis did not converge is recorded as `NaN`
([E-445](../../enhancements_doc/Enhancement-445.md)) — and was *also* counted as
an unresolved output, so the same run said both *"recorded as NaN, not as
results"* (true) and *"those entries are zero"* (false) about the same points. A
reader filtering for zeros would have missed them. An output is now counted as
unresolved only where the analysis itself converged.

## What must not move

The controls are the point of the suite: a real fit is **not** annotated; a
legitimate knob of every spelling (bare device, `@dev[param]`, `temp`, deck
`.param`) still sweeps; a good `list` and a two-knob sweep still parse — the
token after a list is very often the next knob, which is why the list check is
narrowed to tokens that read as a number and are still unusable; a transient
sweep is unchanged, so the KLU guard cannot be mistaken for disabling
refactoring; and a legal `-seed` still pins the run.
