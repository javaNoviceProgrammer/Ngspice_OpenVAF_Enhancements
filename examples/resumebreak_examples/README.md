# resumebreak_examples — Enhancement-880

[E-880](../../enhancements_doc/Enhancement-880.md): F7 of the
[transient stress campaign of 2026-10-12](../../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

With no `minbreak` given, a run starts with ten times `delmin` under XSPICE. `CKTdoJob` puts the
option's 0 back for every job, and a `resume` -- in memory, or from a checkpoint -- re-derived it
as tmax/20 000, the rule of a build without XSPICE: 5e6 times larger on these decks. A pulse edge
shorter than that is skipped, so the continuation stepped over the ends of edges the run had
landed on. All three now take the run's rule.

Checkpoints need Sparse (E-131), so every deck pins it. The checks:
- **[1]** An RC driven by a pulse with 10 fs edges: after the stop, a checkpoint continuation lands
  on every corner the uninterrupted run lands on.
- **[2]** The in-memory resume: the same.
- **[3]** A network of the campaign: the continuation follows the uninterrupted run to 1e-4 of
  the range.
- **[4]** (control) The checkpoint continuation and the in-memory resume are the same run, point
  for point.
- **[5]** (control) With `.option minbreak=1p` the run and the continuation skip the same edge
  ends.

Run: `python3 verify_resumebreak.py` (5 checks per solver). On the E-875 binaries [1] to [3] fail.
