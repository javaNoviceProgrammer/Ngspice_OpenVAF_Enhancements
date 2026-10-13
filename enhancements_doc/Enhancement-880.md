# Enhancement-880: a resumed transient keeps the breakpoint spacing it ran with — a resume, in memory or from a checkpoint, took a minbreak 5e6 times larger and stepped over edges the run had landed on

**Scope:** F7 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice: `spicelib/analysis/dctran.c`: `tran_minbreak`, the run's rule for a `minbreak` that is not
given, used at the start, on a `resume` and on a checkpoint continuation. Stock ngspice-46
behaviour for the in-memory `resume`; the checkpoint branch of
[Enhancement-131](Enhancement-131.md) copied it.

`examples/resumebreak_examples/` (new). **ngspice only.**

**Suites:**
- [`resumebreak_examples`](../examples/resumebreak_examples/): 5 of 5 per solver. On the E-875
  binaries [1] to [3] fail; [4] and [5] are controls.
- `checkpoint`, `ckorder` and `stagedslots` pass.
- The campaign's Family D, rerun: no resumed run and no checkpoint continuation is more than 10×
  less accurate than the uninterrupted run, except one under `ordfix=6`. Before, there were 5
  and 4. Every one of those nine now matches the uninterrupted run's error.
- The full sweep: 584 of 584.

## What was wrong

A checkpoint continuation did not land where the uninterrupted run landed. On a network of the
campaign, driven by a pulse with an 82 fs rise, it was 0.19 off against the exact solution where
the uninterrupted run was 0.011. On an RC driven by a pulse with 10 fs edges, the uninterrupted run
landed on 17 of the 18 corners after the stop, and the continuation on 9. Every rise's end was
stepped over.

`minbreak` is the smallest spacing kept between breakpoints; a source skips a corner closer than
that. With no `.option minbreak`, a run starts with ten times `delmin` in a build with XSPICE, as
ours is, and with tmax/20 000 in a build without it. `CKTdoJob` puts the option's 0 back for every
job, a `resume` included. The resume branch of `DCtran` then re-derived it with tmax/20 000 in
either build, and the checkpoint branch was written the same way. On these decks that is 1e-12 s
against 2e-18 s, 5e6 times larger. The 10 fs edges fell under it, and the continuation skipped
the corners the run had landed on.

The checkpoint continuation is the in-memory resume, point for point, on both the E-875 and the
current binaries. The defect was the resume's, and F7's checkpoint cases were two of its faces.
[Enhancement-877](Enhancement-877.md) fixed three of the five Family D resumes it explained (a
current source's chain). The other two, under `ordfix` and `trbdf2`, were this.

## The change

`tran_minbreak` returns the run's rule: ten times `delmin` with XSPICE, tmax/20 000 without. A run's
start, a `resume` and a checkpoint continuation all take it when `minbreak` is not given. A given
`minbreak` is used as given, as before.

The RC continuation now lands on the same 17 corners as the run, and the campaign network's
continuation follows the uninterrupted run to 1e-6 of the range; it was 0.16.

A continuation is still not the uninterrupted run point for point. `stop when time > t` sets a
breakpoint at t, so the stopped run lands there and restarts its step. The continuation equals a
run with the same stop.

## The checks

`resumebreak_examples`, every deck under `.option sparse` (checkpoints need it):
- **[1]** An RC driven by a pulse with 10 fs edges: after the stop, a checkpoint continuation
  lands on every corner the uninterrupted run lands on.
- **[2]** The in-memory resume: the same.
- **[3]** The campaign network: the continuation follows the uninterrupted run to 1e-4 of the
  range.
- **[4]** (control) The checkpoint continuation and the in-memory resume are the same run, point
  for point.
- **[5]** (control) With `.option minbreak=1p`, the 10 fs edges' ends are skipped by the run and by
  the continuation alike.
