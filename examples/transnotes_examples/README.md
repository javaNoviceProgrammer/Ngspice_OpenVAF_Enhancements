# transnotes_examples — Enhancement-885, Enhancement-886, Enhancement-887, Enhancement-888

[E-885](../../enhancements_doc/Enhancement-885.md), [E-886](../../enhancements_doc/Enhancement-886.md),
[E-887](../../enhancements_doc/Enhancement-887.md) and [E-888](../../enhancements_doc/Enhancement-888.md):
N2, N4, N5 and N6 of the
[transient stress campaign of 2026-10-12](../../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

- **`xmu` below 0.5** is a first-order method, and the step control now sees its first-order
  error (E-885).
- **`newtrunc`'s tolerances**, `ltereltol`, `lteabstol` and `ltetrtol`, say they have no effect in
  a build without the predictor (E-886).
- **An `option` given while a run is paused** is taken by the resumed run when it is read at every
  step, and kept for the next analysis when the run was built on it, on both the `run` and the
  `tran` route; a run started by `run` used to crash on a new `maxord` or solver (E-887).
- **`ordfix`** says it runs without truncation control, and a run under it that diverges stops
  (E-888).

The checks:
- **[1]** (E-885) `xmu=0` takes backward Euler's steps: the points and the value of
  `method=gear maxord=1`.
- **[2]** (E-885) `xmu=0.2` takes more points than trap, and its error is below 1 % of the range.
- **[3]** (E-885, control) `xmu=0.5` is the default run.
- **[4]** (E-886) `newtrunc` says it is ignored and what is used; `ltereltol`, `lteabstol` and
  `ltetrtol` each say they have no effect; a deck without them prints neither.
- **[5]** (E-887) A run started by `run`, given `maxord=3`, the other solver and
  `method=gear maxord=4 dynorder` during a pause, resumes without a crash, names each with the
  value it keeps, and ends where the uninterrupted run ends.
- **[6]** (E-887) A run started by `tran` names and keeps them the same way.
- **[7]** (E-887) `reltol` and `trtol` given during the pause are taken on both routes, which say
  so and end at the same value.
- **[8]** (E-887) The options held for the resumed run take effect at the next analysis.
- **[9]** (E-888) An `ordfix` run says there is no truncation control; `adams ordfix=3` also that
  the order is not A-stable, `gear ordfix=2` not.
- **[10]** (E-888) A stiff network at `adams ordfix=3` stops when a node passes 1e15 V.
- **[11]** (E-888, control) At `gear ordfix=2` the same network runs to the end.

Run: `python3 verify_transnotes.py` (11 checks per solver). On the E-883 binaries [1], [2] and [4]
to [10] fail.
