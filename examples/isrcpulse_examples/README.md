# isrcpulse_examples — Enhancement-877

[E-877](../../enhancements_doc/Enhancement-877.md): F4 of the
[transient stress campaign of 2026-10-12](../../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

A PULSE current source set its next corner only when an accepted point landed on the current
one. A rise shorter than `minbreak` cannot be landed on, so the chain stopped and every later edge
was stepped over: 0.1 ps edges into an RC were 3.0e-2 off from a current source and 2.8e-4 from a
voltage source with the same ODE. The current source now schedules its corners as the voltage
source does, from the time within the period and a per-run break time, with the defaults its own
load uses.

The checks:
- **[1]** 0.1 ps edges into an RC: the current source is within 1.2 times the voltage source's
  error against the exact response, in as many points.
- **[2]** 15 random pulses (seeded): the current and the voltage source put their points at the
  same times.
- **[3]** (control) A pulse with a count of 2: the same grid as the voltage source.
- **[4]** (control) A second `tran` in the same session repeats the first, point for point.
- **[5]** (control) With 1 ns edges both sources land on every corner.

Run: `python3 verify_isrcpulse.py` (5 checks per solver). On the E-875 binaries [1] and [2] fail.
