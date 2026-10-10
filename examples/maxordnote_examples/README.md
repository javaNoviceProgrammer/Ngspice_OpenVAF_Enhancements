# maxordnote_examples — Enhancement-853

[E-853](../../enhancements_doc/Enhancement-853.md): F9 of the
[second robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

The stock order control only toggles Gear between orders 1 and 2. `dynorder` (E-128) and
`ordfix` (E-181) are the ways above 2. `maxord` was accepted up to 6 and range-checked, and
`method=gear maxord=6` was the run of `maxord=2` to the last digit, without a word. A note now
says so.

Trap has no order above 2. `dynorder` and `ordfix` took it to 3, where the coefficient routine
refuses the order and the step ran on the last step's coefficients:
- trap with `dynorder` and `maxord=3` took 19 rejected steps;
- trap with `ordfix=3` ran past 300 s.

Trap now stays at order 2, and its `maxord` has no effect either way.

The checks:
- **[1]** Gear `maxord=6`: the note names `maxord=6`, `dynorder` and `ordfix`, and the run is
  `maxord=2`'s.
- **[2]** (control) No note for Gear `maxord=2`, Gear `maxord=6 dynorder`, or Gear `ordfix=5`.
- **[3]** Trap `maxord=3`: the trap note.
- **[4]** Trap with `dynorder`: `maxord=3` and `6` give the run of `maxord=2`, with no rejected
  step.
- **[5]** Trap with `ordfix=3` and `6`: the run of `ordfix=2`, bit for bit.
- **[6]** (control) Gear `maxord=6 dynorder` still rises above order 2.

Run: `python3 verify_maxordnote.py` (6 checks per solver). On the E-852 binaries [1], [3], [4] and
[5] fail.
