# Enhancement-499 — loop-command arguments, verdicts, and a KLU refactor kind

Round 58 probed the `sweep` / `optimize` fast path again, after Enhancement-498
fixed the transient side. The reuse arithmetic was clean this time. What was
wrong was everything around it — the arguments the commands accept and the
verdict they print — and, underneath both, one genuine memory bug that setup
reuse made reachable.

## 1. A complex refactor handed a real factorisation

`klu_z_refactor` refills an existing factorisation *in place*, walking the L and
U index arrays that `klu_z_factor` built. Handed a **real** `Numeric` object it
walks half-sized arrays with complex strides: it reads and writes past their
ends, and a later `klu_free_numeric` frees whatever it scribbled. The malloc
abort names the object:

```
malloc: *** error for object 0x3ff0000000000000: pointer being freed was not allocated
```

`0x3ff0000000000000` is the IEEE-754 bit pattern of the double **1.0** — a matrix
*value* being freed as a pointer.

The mismatch is reachable because a `Numeric` outlives the analysis that built
it. Every AC / SP / NOISE run is preceded by a real operating point, and
Enhancement-471's setup reuse keeps the matrix standing between sweep points
instead of rebuilding it, so the second and later points arrived holding the
operating point's real factorisation. Without reuse `CKTsetup` rebuilt the matrix
and `SMPcReorder` did a full complex factorisation first, which is why this was
invisible for as long as it was.

| under `.option klu` | before | after |
|---|---|---|
| `sweep -analysis ac` | `0.0` at every reused point | matches a standalone run |
| `sweep -analysis noise` | `0.0` at every reused point | matches |
| `sweep -analysis sp` | **SIGSEGV on 9 of 10 runs** | clean, 10 of 10 |
| `optimize -analysis ac` | fitted `1000`, reported *converged* | fitted `10000`, as every other configuration does |

SPARSE was never affected, and neither was any analysis that stays real: `op`,
`dc`, `tran`, `tf`, `pz` and `disto` were correct throughout, which is what made
the scope so narrow and so easy to miss.

The matrix now records which kind of factorisation its `Numeric` holds, and a
kind change forces a full factorisation instead of a refactor. Both directions
are guarded — a *real* refactor of a complex `Numeric` is wrong the same way
round, and is reachable whenever a transient follows an AC on a circuit whose
matrix was kept standing.

## 2. Four arguments parsed by a weaker parser than the one in the same file

`com_optimize.c` has always had `optnum()` — built on `ft_numparse`, so it
understands SPICE suffixes *and* scientific notation — and uses it for the
parameter bounds, `-target` values and weights, and `-spec` limits. Its integer
options did not: `-maxiter`, `-samples` and `-swarmsize` called `atoi()`, and
`-tol` called `atof()`. Both stop at the first character they cannot use and
return 0 for text.

So `1k` meant 1000 in a bound and **1** in `-maxiter`, on the same command line:

| | evaluations | fitted R1 |
|---|---|---|
| `-maxiter 1000` | 63 | **1500.000** (exact) |
| `-maxiter 1k` | 5 | 1495.000 |
| `-maxiter 2e2` | 7 | 1495.000 |

`-samples 2e2` ran **2** Monte-Carlo samples, and design centering still printed
a yield percentage and a Wilson confidence interval computed from them. `abc` was
accepted as 0 in all four options, in silence.

`sweep lin 2e2` gives 200 points and `montecarlo 2e2` gives 200 samples, so
optimize was the odd one of the three loop commands — and `sweep` had already
grown a strict count parser (`sw_count_arg`) in Enhancement-478 for exactly this
reason. All four now go through the same strict, whole-token parse, and a value
that cannot be used is **refused** rather than repaired: a count or a tolerance
*is* the request, and substituting one answers a different question.

`-seed` had the matching hole. Enhancement-497 taught the `setseed` **command**
to refuse a fractional seed — `setseed 3.7` answers *"Cannot use 3.7 as seed!"* —
but the **option** spelling went straight to `strtoul`, so `-seed 3.7` was
silently the same run as `-seed 3`, and `-seed 0` / `-seed -3` reached `setseed`
as values it refuses, leaving the run unseeded and **not reproducible** while the
author had asked, in writing, for a fixed seed. All four `-seed` sites
(`montecarlo`, `highsigma`, `wcd`, `optimize`) now apply the command's rule.

## 3. "converged" when nothing was optimised

The word describes the search stopping, not the answer being the one the author
wanted, and three ordinary situations produced a confident "converged" with
nothing behind it:

* **the objective never moved.** A parameter the objective cannot depend on — one
  outside the signal path, or a name that does not resolve at all, which prints
  an error and then optimises nothing — ends after three evaluations with the
  **starting value handed back as the fit**. Starting at 1 k, 5 k and 9 k
  returned 1000, 5000 and 9000, each labelled converged.
* **`-target x 0.4 0`.** A zero weight makes the residual identically 0, so the
  command printed `sum-sq residual = 0` — the most convincing number it can
  produce — for a fit that never happened.
* **the answer sat on a search bound**, so the optimum is outside the range given
  and the reported value is a wall, not a minimum.

The tell was available and unused: the objective's spread across the whole run,
and where the answer sits relative to its bounds. Both are now said, as
Enhancement-438 already says it for failed evaluations a few lines below, and as
QPSS-HB says it when it prints *"STALLED above tol — accepted"*.

## 4. The same shape in `sweep`'s knob

`sw_kind()` falls through to `SW_ALTER` for any name it does not recognise. The
comment on that fallback already describes what follows, because the shape was
familiar: `alter` reports "no such device or model name", the sweep runs anyway
over a knob that never moves, and the user is handed a full set of points,
`rc = 0`, and a perfectly plottable **flat curve whose x-axis is named after the
typo**.

Enhancement-435 removed that shape for a subcircuit-local model name and
Enhancement-488 for `temp`; this removes it for every remaining spelling, which
is the same thing Enhancement-431 did for an unresolved `-output`: *a typo, not
data — do not emit the curve.*

A malformed `list` value did it on a smaller scale. `list 1k inf 2k 3k` ran
**one** point and reported `inf`, `2k` and `3k` as unrecognised tokens, though
`list 1k 2k 3k` proves the last two are read without complaint: the list stopped
at the bad token and every remaining value fell through to the argument loop. The
check is deliberately narrow — it fires only for a token that reads as a number
and is still unusable (`inf`, `nan`), because the token after a list is very
often the next knob of a multi-knob sweep.

## 5. `-overlay` discarded the timepoints the solver chose

It resampled onto a **uniform** grid of the same point count as the longest run.
A transient chooses its timepoints adaptively — it puts them where the waveform
moves — so keeping the count and throwing away the placement is exactly
backwards. The overlay of an RC driven by a 0.2 µs pulse reported a peak of
`0.244` where every one of its own runs, and a standalone run, said `0.402`:
**39 % low**, from the same 121 points. The message said "resampled", so the
interpolation was disclosed; losing a feature present in every input was not.

It now resamples onto the **union** of the runs' own timepoints, so no run's
extremum can fall between grid points, and the message says which grid was used.
The union is bounded to a small multiple of the old size — past that the uniform
grid is used as before, because the alternative is an allocation that grows with
the number of sweep points.

The per-point vector names were formatted with `%g`, six significant digits, so
`list 1000.0001 1000.0002 1000.0003` produced **three vectors all called
`vn_1000`**. They were not dropped — `display` listed three — but only one could
be printed or plotted. They now carry the shortest text that reads back as the
exact value, the answer Enhancement-494 settled on for the same class of defect.

## 6. Two warnings that contradicted each other

A point whose analysis did not converge is recorded as `NaN` (Enhancement-445)
*and* was counted as an unresolved output, so one run said both *"recorded as
NaN, not as results"* — true — and *"those entries are zero"* — false — about the
same three points. A reader filtering for zeros would have missed them. An output
is now counted as unresolved only where the analysis itself converged.

## What must not move

The controls carry the weight here, because five of the six fixes are refusals.
A real fit is **not** annotated. A legitimate knob of every spelling — bare
device, `@dev[param]`, `temp`, deck `.param` — still sweeps. A good `list` and a
two-knob sweep still parse. A transient sweep is unchanged, so the KLU guard
cannot be mistaken for disabling refactoring, and the reuse tally is unchanged.
A legal `-seed` still pins the run.

## Verification

`examples/loopguard_examples/` — 49 checks under both linear solvers, **31 of
which fail without the fix** (36 under KLU). Full regression 413/413.
