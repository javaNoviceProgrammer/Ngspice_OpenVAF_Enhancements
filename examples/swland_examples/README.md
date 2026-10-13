# swland_examples — Enhancement-884

[E-884](../../enhancements_doc/Enhancement-884.md): N1, and the switching half of N3, of the
[transient stress campaign of 2026-10-12](../../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

A built-in switch (`sw`, `csw`) turned over wherever a step happened to end. At tight tolerance
the step crept up on the crossing until "Timestep too small"; at loose tolerance the crossing fell
on the step grid, and trap rang at the edge. A switch that turns over inside a step now asks for
the step to be redone at its crossing, keeps its state there, and the step after it starts at
order 1, as after a source's corner.

The checks:
- **[1]** A charge pump whose switches have no hysteresis runs to the end at `reltol=1e-6` and
  `1e-7`.
- **[2]** A `vh=0` switch at a 100 ns step closes at 500 ns and opens at 1500 ns, within 0.3 ns.
- **[3]** With `vh=0.1` and `vh=−0.1` it turns over at the band edge that applies, within 0.5 ns.
- **[4]** A current-controlled switch lands on its crossing, within 0.3 ns.
- **[5]** Family C's seed-9 charge pump under default trap ends within 0.05 % of `reltol=1e-6`, and
  its switch node peaks within 1 % of the supply.
- **[6]** (control) With `vh=0.01` the pump runs at `reltol=1e-6` and ends at 4.24334 V.

Run: `python3 verify_swland.py` (6 checks per solver). On the E-883 binaries [1] to [5] fail.
