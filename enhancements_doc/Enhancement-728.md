# Enhancement-728: a corner whose run stops part way through — a transient aborted on a timestep too small, an interrupt — contributes copies to the `autocorner` combined plot that end where its data ends, nan from there, with a line saying where; and `$autocorner_failed` names the corners whose run failed, made no plot or was interrupted — the partial plot had been resampled onto the nominal's scale with the last computed value held flat to the end, a waveform never computed on the one plot a schematic host draws

**Scope:** F6 of the
[five-options dig of 2026-09-25](../docs/bug_hunts/2026-09-25_five-options-dig.md).
**ngspice only.** `src/frontend/com_sweep.c` (`ac_resample`: the `trunc` argument and
`ac_missing`; `autocorner_run`: `failed[]`, the per-plot line, `$autocorner_failed`;
`ac_clear_results`). [`examples/autocorner_examples/`](../examples/autocorner_examples/)
(section [22], 3 checks, and one more in [9]; 30 per solver). Handbook
[§3.7](../docs/handbook/03-ngspice-workflows.md). The hunt page.

**Suites:** `autocorner` 30 of 30 per solver, both solvers (28 of 30 on the E-727
binaries); `cornerscmd` 24 of 24, `vacorner` 35 of 35, `savecorner` 29 of 29, `writemc`
21 of 21, `savemc` 37 of 37, `osdimc` 49 of 49 unchanged; no new build warnings; full
sweep, run alone.

## What was wrong

A model that divides by zero at the `ss` corner once `$abstime` passes 5 µs, `.option
autocorner`, `tran 1u 10u`:

```
doAnalyses: TRAN:  Timestep too small; time = 4.86308e-06, timestep = 2.5e-19: cause unrecorded.
tran simulation(s) aborted
autocorner: corner ss: the run failed
autocorner: 9 vectors of tran1 and its 2 corner plots into 'autocorner1' (now current): …
```

| plot | length | last time | `v(out_ss)` at index 40, 50, 69 |
|---|---|---|---|
| `tran2` (corner ss, its own) | 44 | 4.863 µs | — |
| `autocorner1` (combined) | 70 | 10 µs | 0.4651163, 0.4651163, 0.4651163 |

The corner's own plot ends where the run did. The combined plot
([E-656](Enhancement-656.md)) is built from the per-corner plots' vectors resampled
onto the nominal's scale, and the failure was counted (`err`, the message) while the
partial plot still existed, so the copy loop took it and the resampler held the last
computed sample beyond the source's range (`sw_interp` answers `y[len-1]` past the end;
the index path clamps). The copy ran to 10 µs, flat at 0.4651163 from 4.86 µs on, and
nothing in the plot said so; a `meas tran … find v(out_ss) at=9u` read 0.4651163 as a
computed value. E-656's check [9] pinned the case where the failed run made *no* plot.

## What changed

- **The failed corners are known** (`failed[c]`): the run returned an error, made no
  plot, or was interrupted — the interrupted corner's plot is partial too.
- **Their copies end where their data ends.** Under `trunc`, `ac_resample` writes nan
  (real, or nan + i·nan) for every point of the nominal's scale past the corner's last
  point (a relative 1e-12 tolerance), and for every index past the source's length
  where no scale is at hand; a corner whose run succeeded is resampled exactly as
  before. Every consumer treats nan as missing: `print` says `nan`, `max` over a range
  reports the maximum where it was computed, a `find … at=` beyond the abort fails
  ("out of interval") instead of reading the phantom, a host that draws the plot
  draws a gap.
- **The banner says where**, once per combined plot and failed corner that left a
  plot:

```
autocorner: corner ss: its tran2 ends at time = 4.86308e-06 of 1e-05, where the run stopped; its copies in 'autocorner1' are nan from there
```

  (an `op` plot's point scale is not reported: a failed `op` makes no plot).
- **`$autocorner_failed`** names the corners whose run failed, made no plot or was
  interrupted, space-separated, and is unset when every corner ran; a plain run clears
  it with the other variables; the raw-file path sets it too.

## Verification

`autocorner` [22], the model above under the option: the corner is said to have failed
and where its plot ends (the abort point is the solver's: Sparse stops at 4.863 µs with
44 points in the corner's own plot, KLU at 5 µs with 81, taking smaller steps into the
singularity), `$autocorner_failed` is `ss`, `v(out_ss)[69]` prints `nan` and
`v(out_ss)[9]` 0.4651163; one 70-point scale still serves the combined plot, the `ff`
copy is finite throughout, the corner's own plot is untouched; a clean pass prints no
such line, leaves the variable unset and computes the `ss` copy to the end. [9]: a
corner that made no plot is named in `$autocorner_failed`. On the E-727 binaries the
two checks that pin the new behaviour fail; the other two pin what was already so.

By hand: the hunt's harness E [E3] deck on both binaries, with `find v(out_ss) at=4u`
(0.4651163 on both), `at=9u` (0.4651163 before, "out of interval" now) and `max … to=9u`
(the maximum at 4.86 µs now); the seven suites; the sweep.

## What this does not do

- The corner's own plot is untouched: it ends where the run did and holds no nan.
- A corner whose run *succeeded* is resampled as before, held at its last value past
  its scale; the rule follows the failure, not the scale (a transient runs to its stop
  time, an ac to its last frequency, so the two coincide).
- A `meas` at a time beyond the abort fails with `com_measure2`'s "out of interval",
  its wording for a nan it met; the message is not changed here.
- The `corners` command ([E-655](Enhancement-655.md)) has its own loop and `-output`
  table, where a failed corner's cells were nan already; nothing there changes.
- How a host draws a nan point is the host's.
