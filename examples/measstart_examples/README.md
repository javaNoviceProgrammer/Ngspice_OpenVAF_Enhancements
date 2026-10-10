# measstart_examples — Enhancements 848 and 849

[E-848](../../enhancements_doc/Enhancement-848.md) and [E-849](../../enhancements_doc/Enhancement-849.md):
F4 and F5 of the
[second robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

Both defects are at the start of a measurement window.

- **E-848:** AVG, INTEG and RMS with `from=` overwrote the first sample inside the window with
  the value interpolated at `from`. That sample never entered the sum: the trapezoid ran from
  `from` straight to the second sample. On a triangle whose corner is that sample, AVG and
  INTEG were 3e-4 low. The value at `from` is now a point of its own, ahead of the sample.
- **E-849:** WHEN spent a window's first sample on remembering a value and its second on
  classifying the side, so a crossing between those two samples was lost. With several
  crossings, the next one was reported: `fall=1 td=` gave a fall 0.4 µs late. This affected:
  - FIND..WHEN and TRIG with TD;
  - WHEN with FROM;
  - dc and ac sweeps entering their window through FROM or TO.

  The window now opens at its boundary. The value there is interpolated, the side is
  classified there, and the first interval is evaluated. Only the interval from sample 0, the
  operating-point interval that E-418 skips, is still not evaluated.

The checks take `td` and `from` from the samples of a first run, so they do not depend on where
the timestep control puts them:
- **[1]** AVG and INTEG over a window opening just before a corner sample: exact.
- **[2]** RMS of a ramp-then-flat over that window: the trapezoid on the ramp, exact after it.
- **[3]** (control) `from` on the corner sample, and no window.
- **[4]** WHEN `td=` with the crossing between the first two samples after TD.
- **[5]** A crossing past TD, before the first sample after it, is found. (control) A crossing
  before TD is not counted.
- **[6]** FIND..WHEN, TRIG/TARG, a two-vector WHEN with that TD, and WHEN `from=`.
- **[7]** Several crossings: `fall=1 td=` reports the first fall after TD.
- **[8]** ac: WHEN `from=` on a low-pass.
- **[9]** dc: `from=` on a rising sweep, `to=` on a falling one, and `from=` on nested sweeps.
- **[10]** (control) Nested dc sweeps without a window entry.
- **[11]** (control) WHEN without `td`, and with a `td` well before the crossing.

Run: `python3 verify_measstart.py` (18 checks per solver). On the E-844 binaries the 14 checks
of the defects fail.
