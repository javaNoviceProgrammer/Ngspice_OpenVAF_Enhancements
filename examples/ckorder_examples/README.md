# ckorder_examples — Enhancement-879

[E-879](../../enhancements_doc/Enhancement-879.md): F6 of the
[transient stress campaign of 2026-10-12](../../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

`loadstate` sets the circuit up before `CKTdoJob` copies the task's options, so the circuit had the
default `maxord` of 2, and every checkpoint taken with `maxord` above 2 was refused: "checkpoint
does not match this circuit (equations 4 vs 4, states 2 vs 2)", the two counts that matched. The
method and `maxord` are now copied before the setup, and the message names the order.

Checkpoints need Sparse (E-131), so every deck pins `.option sparse`. The checks:
- **[1]** `gear maxord=3`: the checkpoint restores in a fresh process, and v(b) at 2.5 µs is the
  uninterrupted run's to 1e-6.
- **[2]** `adams maxord=4`, and `gear maxord=6` with `dynorder`: the same.
- **[3]** `sdirk`: the same.
- **[4]** A checkpoint taken at `maxord=3` and loaded into a deck at `maxord=2` is refused with
  "maximum order 3 vs 2" in the message.
- **[5]** (control) `maxord=2` restores, as before.

Run: `python3 verify_ckorder.py` (5 checks per solver). On the E-875 binaries [1] to [4] fail.
