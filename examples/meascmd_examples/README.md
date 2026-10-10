# meascmd_examples — Enhancement-851

[E-851](../../enhancements_doc/Enhancement-851.md): F7 of the
[second robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

The `meas` command stored its result with `let name = %e`, 7 significant digits. The same
`.meas` card's result had 16 (E-802). A vector named after `val=`, `at=`, `from=` or `to=` was
put back into the line the same way. Two crossings 1.8 fs apart read the same time, and their
difference was 0. `find ... at=t2` was read at a rounded `t2`.

All three now carry 17 significant digits. Both readers are correctly rounded (E-643), so the
vector holds the measured double itself.

The checks:
- **[1]** The command's FIND equals the same `.meas` card's, bit for bit.
- **[2]** Two crossings 1.8 fs apart: the commands' difference is the cards' difference.
- **[3]** `find v(1) at=t2`, `t2` a vector: v(1) at `t2` is 0.50000001.
- **[4]** (control) The card's result is the linear interpolation of the samples, to 1e-15.

Run: `python3 verify_meascmd.py` (4 checks per solver). On the E-844 binaries [1] to [3] fail.
