# Enhancement-887: an `option` given while a run is paused is applied or held, and said — `option maxord=3` or `option klu` before `resume` crashed a run started by `run`, and a run started by `tran` ignored every option without a word

**Scope:** N5 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice:
- `frontend/spiceif.c`, `if_run`: the options a run starts with are kept; on `resume` the ones
  changed since are applied or held, with a note.
- `include/ngspice/ftedefs.h`: `ci_runopts`.
- `frontend/runcoms2.c`: freed with the circuit.

`examples/transnotes_examples/` (new, shared with [E-885](Enhancement-885.md),
[E-886](Enhancement-886.md) and [E-888](Enhancement-888.md)). **ngspice only.**

**Suites:**
- [`transnotes_examples`](../examples/transnotes_examples/): [5] to [8] are this enhancement's,
  11 of 11 per solver. On the E-883 binaries [5] to [8] fail.
- `checkpoint`, `ckorder`, `resumebreak`, `stagedslots`, `autosave`, `idtassert` and `writemc`
  pass.
- The full sweep: 587 of 587.

## What was wrong

`option` writes the default task's options. What a paused run did with them depended on how the
run started.

- **Started by `run`** (the deck's own `.tran`): the run's task IS the default task, and
  `CKTdoJob` copies every option from it again at a resume. A new method or `maxord` met history
  slots the run had not allocated, and `option klu` met a matrix built for Sparse:
  - `option maxord=3`, `option method=gear maxord=4 dynorder`: a segmentation fault in `CAPload`;
  - `option klu`: one in `NIiter`.

  `option method=gear` switched the method mid-run, and `option reltol=1e-6` was taken. None of
  it was said.
- **Started by `tran`** (from `.control`): the run has its own copy of the task, made at the
  command, and nothing given during the pause reached it. Method, `maxord`, `dynorder`, the
  solver and `reltol` all gave the uninterrupted run's 1 346 iterations, without a word. This is
  what the campaign saw: its sessions started their runs with `tran`.

## The change

Both routes now resume alike. When a run starts, `if_run` keeps a copy of its options; at
`resume` it compares the default task, where `option` writes, with that copy. So an option set
before the run is not reported, and only what changed during the pause is.

- **Taken by the resumed run:** the options read afresh at every step. These are `reltol`,
  `abstol`, `vntol`, `chgtol`, `trtol`, `xmu`, `trgamma`, `itl4`, `gmin`, `gshunt`, `pivtol`,
  `pivrel`, `absdv`, `reldv`, `bypass`, and the Newton aids `nodedamping`, `linesearch` and
  `trustregion`.
  ```
  Note: the resumed run takes reltol = 1e-06 and trtol = 0.1, given during the pause.
  ```
- **Held at the run's values:** the options the run was built on. These are the method,
  `maxord`, `ordfix`, `dynorder`, `temp`, `tnom`, `cshunt` and the solver with its `klu_*`
  settings. They take effect from the next analysis.
  ```
  Note: method = gear, maxord = 4 and dynorder on, given during the pause, take effect from the next analysis; the resumed run keeps method = trap, maxord = 2 and dynorder off, which it was built on.
  ```
  On the `run` route the default task gets the values given back after the resumed run, for the
  next analysis. A held option is named once, however many pauses follow.

A checkpoint's continuation (`loadstate`) starts from the options set at that moment, which
[E-879](Enhancement-879.md) built its circuit on. It compares nothing, and is the start a later
pause compares against.

## Measured

On an RC with an inductor, stopped at 1 µs of 4 µs, with `delete all` before the resume:

| given during the pause | E-883, `run` | E-883, `tran` | E-887, both |
|---|---|---|---|
| `maxord=3` | segmentation fault | kept, silently | kept, named; 4.44486e-7, the uninterrupted value |
| `klu` | segmentation fault | kept, silently | kept, named |
| `method=gear maxord=4 dynorder` | segmentation fault | kept, silently | kept, named |
| `method=gear` | switched mid-run, silently | kept, silently | kept, named |
| `reltol=1e-6 trtol=0.1` | taken (3 385 iterations), silently | ignored (887) | taken on both, named; 4.51376e-7 |

The next analysis after the resumed run, with `method=gear maxord=3 klu` given during the pause,
ends at 4.212264e-7 on both routes. That is the value of a fresh run with those options.

## The checks

`transnotes_examples`:
- **[5]** A run started by `run`, given `maxord=3`, the other solver, and
  `method=gear maxord=4 dynorder` during a pause, resumes without a crash. It names each with the
  value it keeps, and ends where the uninterrupted run ends.
- **[6]** A run started by `tran` names and keeps them the same way.
- **[7]** `reltol` and `trtol` given during the pause are taken on both routes, which say so and
  end at the same value.
- **[8]** The options held for the resumed run take effect at the next analysis, on both routes.
