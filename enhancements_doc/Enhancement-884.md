# Enhancement-884: built-in switches land on their crossing — a switch without hysteresis ended a charge pump with "Timestep too small" at reltol 1e-6, and a switch at a 100 ns step closed 11 ns late

**Scope:** N1 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md),
and the switching half of its N3.

ngspice:
- `spicelib/devices/sw/swtrunc.c` and `csw/cswtrunc.c`: a switch that turned over in the point
  under way asks for the point to be redone at its crossing.
- `sw/swload.c` and `csw/cswload.c`: the switch keeps its accepted state on that landing.
  `cswload.c` also stores the controlling current, which stock ngspice left out.
- `spicelib/analysis/cktterr.c`: `CKTlandRequest`, the landing request any device makes.
- `spicelib/analysis/dctran.c`: the retry takes the earliest request; a switch's landing is
  redone from the accepted solution, and the step after it starts at order 1.
- `osdi/osditrunc.c`: [Enhancement-759](Enhancement-759.md)'s Verilog-A landing goes through the
  same request.
- `include/ngspice/cktdefs.h`, `sw/swdefs.h`, `csw/cswdefs.h`.

`examples/swland_examples/` (new). **ngspice only.**

**Suites:**
- [`swland_examples`](../examples/swland_examples/): 6 of 6 per solver. On the E-883 binaries [1]
  to [5] fail; [6] is a control.
- `argguard`, `ctrlnode`, `dcpath`, `gatecheck`, `sensrestore`, `solvercore` and `warnphysics`
  (the suites with built-in switches) pass.
- `evtedge` (24 of 24), `simctrl`, `discontinuity` and `finalstep` (E-759's landing) pass.
- The full sweep: 587 of 587.

## What was wrong

A charge pump, two switches with `vh=0` driven by complementary 1 ns ramps, ran at
`reltol=1e-3` and `1e-5` and ended "Timestep too small" at `1e-6` and `1e-7`, under both
solvers. Family C of the campaign saw it in 34 of 40 charge-pump references (one more ran past
120 s) and 5 of 40 boost references. Any hysteresis seemed to cure it.

Nothing placed a point at a switch's crossing. The step that crossed was judged by the
truncation estimate, which at a crossing measures the jump in current the switching brings. The
point was rejected, and the retry, sized by that estimate, fell short of the crossing and was
accepted. The next point crossed again. The accepted points crept up on the crossing, each
closer than the last: 4.9984, 4.99994, 4.99998 … × 10⁻¹⁰ s. At `reltol=1e-6` the steps reached
1e-16 s, where the rounding in Δq/h is larger than Newton's tolerance, and every retry failed to
converge. Hysteresis did not cure it: a `vh=0.01` switch crept the same way, in 1e-14 s steps,
and got across.

At looser tolerance the crossing step was accepted on the grid. A built-in `sw` driven by a 1 µs
ramp, at a 100 ns step, closed 11.2 ns late and opened 19.7 ns early; E-759's table has the same
lag, 31.2 ns, on its own deck ("plain `if`, built-in `sw`: unchanged").
Trap integrated the crossing step with the new state at its end, and rang. The seed-9 charge
pump of Family C (N3) put its switch node at 2.66 V on a 2.49 V supply, and its output 1.1 %
off.

## The change

A switch whose state changed between the accepted point and the attempt finds where its control
crossed the band edge that turned it over. The control is interpolated linearly between the two
points; the edge is `vt + vh` or `vt − vh`, by SWload's own rule, for either sign of `vh`. The
switch then asks for the attempt to be redone at the crossing, through E-759's landing protocol.
On that landing it keeps its accepted state. The circuit is integrated with the old state up to
the crossing and with the new one from it, and no gap is left to creep across. The landing is
redone from the accepted solution, not the rejected attempt's: a switch with hysteresis keeps
the state its first iterate took while the control stays in the band.

The step after the landing is the one the switch turns over in. It is taken at order 1, and at
a tenth of the landing step at most, as after a source's corner. No switch asks for a landing
from the landing itself, from the step after one, or for a crossing in the first thousandth of
the step.

`CKTlandRequest` takes the earliest request, and `dctran` uses it as the retry's step,
whatever a device type later in the table estimated. The switch comes before the OSDI devices
and after the capacitors in that table. E-759's OSDI request goes through it too; with OSDI
devices last, their landings are unchanged. Under `ordfix` the request replaces the pinned
step, which would have redone the point at twice the step and crossed again.

The current-controlled switch had no landing to make. CSWload did not store its controlling
current ("without this statement truncation is not used, as with SW. But test are needed"), so
CSWtrunc saw no change. It is stored now, for the landing. The approach limit that read it, which
never ran, is left out.

## Measured

| | E-883 | E-884 |
|---|---|---|
| charge pump, `vh=0`, `reltol=1e-6` / `1e-7` | "Timestep too small" | 4.243345 V / 4.243344 V, 80 landings (one per crossing) |
| the same, iterations at `1e-3` / `1e-5` | 42 042 / 50 004 | 44 616 / 46 474 |
| `sw`, `vh=0`, 100 ns step: closes / opens (exact 500.00 / 1500.69 ns) | 511.22 / 1480.98 ns | 500.07 / 1500.78 ns |
| `vh=0.1` (600.00 / 1600.69 ns) | 591.22 / 1600.98 ns | 600.22 / 1600.74 ns |
| `vh=−0.1` (400.00 / 1400.69 ns) | 391.22 / 1400.98 ns | 400.22 / 1400.74 ns |
| `csw` (500.00 / 1500.69 ns) | 511.22 / 1480.98 ns | 500.07 / 1500.78 ns |
| seed-9 pump, default trap (tight: 1.183447 V) | 1.196523 V | 1.183490 V |
| its switch node's peak (supply 2.4932 V) | 2.661 V | 2.502 V |
| its `reltol=1e-6` run, iterations | 57 515 | 35 503 |
| its `method=trbdf2` run | 1.198507 V | 1.184133 V |

Family C, rerun on both binaries (the three templates with switches):

- **Charge pump and boost references** (trap, `reltol=1e-6`): all 80 end. On E-883, 39 ended
  "Timestep too small" and one ran past 120 s.
- **The 160 runs under random settings:** 4 fail (were 11). Each of the four pins an order that
  is not A-stable with `ordfix`, as N6 describes ([E-888](Enhancement-888.md)).
- **The Schmitt trigger:** all 120 runs end, on both binaries.

The waveforms were checked against each binary's tight reference, by the rms error over time.
On the charge pump the median error ratio, E-884 over E-883, is 0.33 (21 of 35 runs better by
more than 2×, 2 worse). On the Schmitt trigger it is 1.0 (16 better, 3 worse), and on the boost
0.99 (9 better, 3 worse). The runs that are worse are:
- `ordfix=6`;
- boost converters at loose tolerance whose result is set by trap's phase error on a ringing
  switch node. On seed 343 the two binaries differ by 18 % and 3 % at default tolerance, the
  other way round at `reltol=1e-2`, and agree to 0.01 V at `1e-4` and `1e-5`.

## The checks

`swland_examples`:
- **[1]** The charge pump with `vh=0` runs to the end at `reltol=1e-6` and `1e-7`.
- **[2]** A `vh=0` switch at a 100 ns step closes at 500 ns and opens at 1500 ns, within 0.3 ns.
- **[3]** With `vh=0.1` and `vh=−0.1` it turns over at the band edge that applies, within 0.5 ns.
- **[4]** A current-controlled switch lands on its crossing, within 0.3 ns.
- **[5]** The seed-9 pump under default trap ends within 0.05 % of `reltol=1e-6`, and its switch
  node peaks within 1 % of the supply.
- **[6]** (control) With `vh=0.01` the pump runs at `reltol=1e-6` and ends at 4.24334 V.

## Limits

- The crossing is found by linear interpolation of the control. A curved control lands near,
  not on, its crossing; the switch keeps its state there either way, and turns over in the next
  step.
- The step after a landing takes the new state from its start. Its truncation estimate follows
  a long landing step, and a fast transient inside it (a picosecond time constant behind a 1 Ω
  switch) is crossed in one backward-Euler step rather than resolved; the point after it is
  where the transient ends.
- `trbdf2` and `sdirk` keep their own order across the landing; on the seed-9 pump `trbdf2`'s
  switch node still peaks at 2.57 V.
- An XSPICE digital or `aswitch` code model is not a built-in switch and does not land.
