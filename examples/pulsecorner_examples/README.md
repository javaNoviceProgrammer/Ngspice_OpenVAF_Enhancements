# pulsecorner_examples — Enhancement-875

[E-875](../../enhancements_doc/Enhancement-875.md): found while folding F2 of the
[transient stress campaign of 2026-10-12](../../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

A PULSE voltage source schedules its next corner from the time within its period,
floor((t − TD)/PER). Landed on the fifth rise of a campaign network, (t − TD)/PER was
3.999999999999843: the point read as the end of the fourth period, the next pulse looked 3.6e-21 s
away, under `minbreak`, and the rise's end went unscheduled until the next point. A step that went
past it skipped it; trap's truncation estimate usually rejected such a step, `trbdf2`'s and
`sdirk`'s did not. A repeating PWL had the same arithmetic and also wrapped only past its last
knot. A time within `minbreak` of the period's end now counts as the next period's start.

The checks:
- **[1]** That pulse into an RC: every corner is a point under trap, `trbdf2` and `sdirk`.
- **[2]** 20 random pulses (seeded) under trap: every corner is a point.
- **[3]** A repeating PWL with an edge at each repeat's start: every knot is a point under trap.
- **[4]** 20 random repeating PWLs (seeded) under `trbdf2`: every knot is a point.
- **[5]** (control) The pulse of [1] under trap at `reltol=1e-5` is within 0.1 % of the exact RC
  response.

Run: `python3 verify_pulsecorner.py` (5 checks per solver). On the E-872 binaries [1] to [4] fail.
