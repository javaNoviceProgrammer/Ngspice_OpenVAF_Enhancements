# Enhancement-899: a self-heating built-in HICUM survives a second analysis and a cold iterate — its thermal node ended ngspice at the second analysis of a small circuit

**Scope:** found while digging into F2 of the
[analyses correctness campaign of 2026-10-16](../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md)
([E-896](Enhancement-896.md)). One of the four is a regression of [E-889](Enhancement-889.md),
whose device convergence tests made the HICUM test's slips decisive.

ngspice:
- `spicelib/devices/hicum2/hicum2setup.c`, `hicum2defs.h`: the internal thermal node is
  deleted when the setup made it.
- `spicelib/devices/hicum2/hicumL2temp.cpp`: the lower branch of `clip_temperature`.
- `spicelib/devices/hicum2/hicum2conv.c`: `Veie`'s sign, `ibpbihat`'s own term, `ibpcihat`'s
  voltage.
- `spicelib/devices/hicum2/hicumL2.cpp`: the junction start.

**ngspice only.**

**Suites:**
- [`hicum2_examples`](../examples/hicum2_examples/): checks [12] to [16]. 16 of 16 per
  solver; on the E-895 binaries 15 of 16 fail.
- `convtest`, `warmstart`, `failacct`, `linesearch`, `bsrcconv` and `oprobust` pass.
- The full sweep: 592 of 592.

## What was wrong

**The thermal node at the second analysis.** Every new analysis unsets and sets up the
circuit. `HICUMunsetup` decided whether the thermal node was the internal one its setup creates
by testing `HICUMtempNode > 6`.
- In a circuit of a few nodes the internal node has a smaller number and outlived the unsetup.
  The next analysis ended ngspice: "Internal Error: incomplete CKTunsetup()", exit 1. Three
  lines suffice, a supply, a base drive and a self-heating HICUM, with an `op` followed by an
  `ac`, or by another `op`.
- A thermal terminal the user connected, numbered past 6, was deleted instead: "CKTdltNNum()
  removing a non device-local node", exit 1.

**The temperature clip.** Below the lower limit the smooth clip read:

```
Tdev = TMIN+CONSTCtoK+exp(T-TMIN+CONSTCtoK-1.0);
```

That is exp(T + 372 K), which overflows. The upper branch's mirror is
exp(T − (TMIN + 273.15) − 1). Any iterate that cooled a self-heating device past −99 °C made
its temperature 1e236 and then NaN: "The temperature limiting function received NaN". A stage
at −120 °C ambient reported its collector at 0.117 V, where the Verilog-A model gives 2.998 V.
Newton iterates reach such temperatures on the way to an ordinary operating point.

**The convergence test.** E-889 made the device tests decide, and `HICUMconvTest` had three
slips:
- **`Veie`** read V(e) − V(ei), the reverse of the stored V(ei) − V(e). With `re` given and
  `flsh=2`, every step predicted 4·Veie²/re of power that was not there. A stage E-888 solved
  found no operating point from E-889 on, through every aid.
- **`ibpbihat`** left out its own term, `Ibpbi_Vbpbi·ΔVbpbi`.
- **`ibpcihat`** multiplied `Ibpci_Vbpci` by ΔVbici instead of ΔVbpci.

**The junction start.** The first iteration puts Vbiei at `tVcrit`, the critical voltage of
`ibeis`, the b-e diode's saturation current. When the transfer saturation current c10/qp0 is
far larger, that start puts amperes through the transistor: with `ibeis` 1e4 below c10/qp0,
1.09 V and 180 A. With the Jacobian corrected (E-896), one random card that E-895 had solved
from there by luck stopped converging.

## The change

- `HICUMtempNodeInternal`, set when `HICUMsetup` makes the node; `HICUMunsetup` deletes the node
  it made, whatever its number, and nothing else.
- `exp(T-(TMIN+CONSTCtoK)-1.0)`, continuous with T, and with slope 1, at TMIN + 1 K.
- `Veie` = type·(V(ei) − V(e)); `ibpbihat` has `Ibpbi_Vbpbi·ΔVbpbi`; `ibpcihat` has ΔVbpci.
- The junction starts at the lower of `tVcrit` and the critical voltage of c10/qp0. The limiting
  keeps `tVcrit`, as the Verilog-A model's `$limit` does.

## The checks

`hicum2_examples`:
- **[12]** Two analyses on a three-node circuit with an internal thermal node. E-895:
  "incomplete CKTunsetup()", exit.
- **[13]** Two analyses with the thermal terminal on a node numbered past 6: the same
  temperature both times. E-895: "CKTdltNNum() removing a non device-local node", exit.
- **[14]** `flsh=2` with `re`: solves, within 1e-4 of the Verilog-A model. E-895: no operating
  point; E-888 solved it.
- **[15]** Self-heating at −120 °C: within 1e-4 of the Verilog-A model, no NaN. E-895: 0.117 V
  against 2.998 V.
- **[16]** `ibeis` 1e4 below c10/qp0: solves in at most 11 iterations. E-895: 14.

150 random cards, with E-896 to E-899 together:
- E-895 solves 130, 32 of them through a convergence aid. Now 149 solve, 6 through an aid.
- Where both solve, the Newton iterations total 28,566 on E-895 and 10,463 now.
- The new junction start alone, with everything else in place, takes the total from 126,007 to
  73,947 iterations. It takes fewer on 117 cards and more on 12 (one from 205 to 2,680), and it
  changes no operating point by more than 1e-12 V.

## Limits

One card of the 150 still finds no operating point, as on E-888 and E-895. It combines
avalanche with `kavl`, rbi, lateral spreading and self-heating. The Verilog-A model solves it.
