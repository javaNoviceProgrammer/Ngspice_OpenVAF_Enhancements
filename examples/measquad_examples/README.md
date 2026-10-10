# measquad_examples — Enhancement-855

[E-855](../../enhancements_doc/Enhancement-855.md): F11 of the
[second robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

AVG integrated by trapezoids. INTEG and RMS used Simpson's 3/8 or 1/3 rule on runs of equal
steps, and trapezoids elsewhere. So INTEG/(to−from) and AVG over one window differed, by 2e-3 on
a sampled sine, where E-302 calls them the same quantity.

AVG now integrates its points with INTEG's rule, through one function the three share. A falling
dc sweep is integrated upward, as INTEG walks it.

The checks:
- **[1]** A sampled sine: AVG = INTEG/(to−from) over a window.
- **[2]** (control) The same across PWL corners, where the two rules already agreed.
- **[3]** The same over the whole run, without a window.
- **[4]** The sine's AVG is within 5e-4 of the analytic average.
- **[5]** A dc sweep, rising and falling: AVG = INTEG/(to−from).
- **[6]** (control) A constant and a ramp: AVG exact.

Run: `python3 verify_measquad.py` (7 checks per solver). On the E-852 binaries [1], [3], [4] and
both [5] fail.
