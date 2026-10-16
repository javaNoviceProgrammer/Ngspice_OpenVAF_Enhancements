# Enhancement-889: the device convergence tests decide, and a Verilog-A device has one — a diode between two 100 V nodes converged 0.68 V forward with 2.47 mA of KCL error

**Scope:** F1 of the
[nonlinear correctness campaign of 2026-10-15](../docs/bug_hunts/2026-10-15_ngspice-openvaf-r-nonlinear-correctness-campaign.md).

ngspice:
- `maths/ni/niconv.c`: the device tests see the new solution, and their count is the answer.
- `osdi/osdiload.c`: `OSDIconvTest`, registered in `osdi/osdiinit.c` and declared in
  `osdi/osdiext.h`.
- `osdi/osdicallbacks.c`: `osdi_residual_abstol`, declared in `include/ngspice/osdiitf.h`.
- `include/ngspice/cktdefs.h`: `CKTconvLoaded`.

`examples/convtest_examples/` is new. **ngspice only.**

**Suites:**
- [`convtest_examples`](../examples/convtest_examples/): 9 of 9 per solver. On the E-888
  binaries 7 of 9 fail.
- `warmstart`, `failacct`, `linesearch`, `bsrcconv` and `oprobust` pass. These are the suites
  that move when Newton's phases or its guard change.
- The full sweep: 588 of 588.

## What was wrong

A Newton iteration ends with two tests:
- **The node test:** no unknown moved more than reltol of itself plus `vntol` (or `abstol`).
- **The device tests:** no device current moves more than reltol of itself plus `abstol` over the
  step just solved. That change is the device's share of the KCL residual at the point it was
  loaded at, and that point is the one `NIiter` reports.

Thirty devices have a device test, and none of them ever decided anything:
- **The count was thrown away.** `NIiter` assigns `NIconvTest`'s return value to `CKTnoncon`.
  `NIconvTest` returned `CKTconvTest`'s return code, which is `OK` after a device has counted
  itself unconverged, so the count was overwritten with 0. This holds for the MOSFETs of levels 1
  to 9 as well, whose tests read the right vector.
- **Most tests read the wrong vector.** 22 of the 30 read their voltages from `CKTrhsOld`: the
  diode, the BJTs, VBIC, HICUM, BSIM1 to BSIM4, the SOI models, HiSIM and the B source. VDMOS's body
  diode does too. Before `NIiter`'s swap, `CKTrhsOld` still holds the load point. The "new"
  voltage equalled the stored one, and the predicted change was 0 unless limiting had moved it.
- **A Verilog-A device had no test at all.**

So only the node test was left. At 100 V it allows 0.1 V a step: four thermal voltages.

A diode across a 794 kΩ resistor, both between node 3 (driven to 100 V) and node 4, which
nothing else touches. The only solution is 0 V across the pair. The E-888 run converged in 3
iterations with:
- the diode 0.6786 V forward, carrying 2.47 mA;
- the resistor carrying 0.86 µA.

Node 4's KCL was off by the whole diode current. The Verilog-A diode did the same. So did an npn's
base across the resistor (0.552 V), and a level-1 MOSFET's bulk junction started forward by a
nodeset (0.673 V). The campaign's Family A found two such networks among 500:
- seed 1436, a Verilog-A diode between 183 V nodes;
- seed 1031, at 65 V, where the built-in and Verilog-A runs of the same network disagreed by 1.9 V.

At ordinary voltages the same gap shows up as accuracy. The last step may be reltol of the node
voltage, which on a junction is 20 times reltol of its current. A `dc temp` sweep of one diode on
2.69 µA reported 0.5215276 V at −31.68 °C against an exact 0.5210549 V: its current 2 % off.

## The change

`NIconvTest` runs the device tests on the new solution. It points both `CKTrhs` and `CKTrhsOld`
at it while `CKTconvTest` runs, so a test reads the same values whichever vector it names. A
device that counts itself unconverged makes the iteration unconverged.

Three details:
- **Rounding is not a step.** An unknown that moved by no more than 64 ε of itself is shown at
  its load point. Without this, Family A's networks 1111, 1214, 1399 and 1445 never converged
  (39 000 iterations). In each, an ideal source forward-biases an npn by 2 V, so its collector
  current is the near-cancelling difference of two 1e13 A transport currents. A one-ulp move of
  `vbe` then predicted a 0.013 A change, against a tolerance of 1e-5 A. 64 ε of a node voltage
  moves a junction's current by under 1e-10 of itself, so no real step is hidden.
- **Not in MODEINITFIX.** There a device marked `off` is held at 0 V whatever the solution says.
  The load routines exempt it from their limiting count for the same reason, and MODEINITFLOAT
  always follows to confirm the point. Run in MODEINITFIX, the test held a diode marked `off`,
  which its circuit drives forward, until dynamic gmin stepping took over at 351 iterations.
- **`CKTconvLoaded`** carries the load point to `OSDIconvTest`, since `CKTrhsOld` no longer does
  while the tests run.

`OSDIconvTest` gives a Verilog-A device the test a built-in device has. For each row of the
instance's resistive system it computes the predicted change, ΔI = Σ J·Δx, where J is
`write_jacobian_array_resist`'s Jacobian and Δx the step. That change must be within reltol of
the row's current plus the `abstol` of the row's flow nature, unless the user set `abstol`:
- An internal row nets to zero at the solution, so its own current is no scale. It is judged
  against the instance's largest terminal current, as the built-in diode judges its junction
  behind the series resistance.
- Rows of a potential equation, a flow unknown's row, are not tested; nor are the rows of a model
  whose every resistive entry is constant. Neither has a built-in counterpart with a test.
- An instance none of whose unknowns moved is not visited. That is every instance of a linear
  circuit after its first solve.

## The checks

`convtest_examples`:
- **[1]** The diode across the resistor between two 100 V nodes converges off: |vd| < 1 µV and
  |I(r)| < 1 pA. E-888: 0.679 V and 2.47 mA.
- **[2]** The same with a Verilog-A diode. E-888: 0.679 V.
- **[3]** The same with a Verilog-A diode behind a series resistance on an internal node.
  E-888: 0.679 V.
- **[4]** An npn's base across the resistor: |vbe| < 1 µV. E-888: 0.552 V.
- **[5]** A level-1 MOSFET's bulk junction, started forward by a nodeset: |vbd| < 0.1 mV.
  E-888: 0.673 V.
- **[6]** The `dc temp` sweep at default tolerances is within 30 µV of the same sweep at
  `reltol=1e-9` at every point. E-888: 0.47 mV.
- **[7]** Family A's network 1111 converges in 23 iterations.
- **[8]** The diode marked `off` converges in at most 20 iterations, within reltol of the point it
  reaches without `off`. E-888: 0.12 mV apart, 0.5 % of the current.
- **[9]** A closed Verilog-A switch between two 100 V nodes converges in at most 10 iterations.

Across the campaign's families:
- **Family A** (500 networks, built-in and Verilog-A, under KLU and Sparse): every run still
  solves. Network 1031's built-in and Verilog-A runs now agree to 4 µV.
- **Family D** at default tolerances: the worst diode error falls from 8.1e-4 of the voltage to
  5.8e-5, inside reltol of the current.

## Cost

Newton takes the iterations the tests ask for:
- **Family A:** 1.1 % more iterations in total (6601 to 6672 built-in, 6279 to 6328 Verilog-A).
  79 of 1000 runs take more, at most 12 more, and those are the networks that converged falsely
  before.
- **The benchmark suite's transients**, run ten times longer:
  - the diode rectifier and the RC ladder: unchanged iterations and waveforms;
  - the built-in BSIM4 ring oscillator: 2.25 to 2.56 iterations a point, 13 % more time. Its
    frequency, against a `reltol=1e-6` run, moves from 5.1e-4 to 4.4e-4 off;
  - the Verilog-A BSIM4 ring oscillator: 2 % more iterations and 6 % more time;
  - the linear Verilog-A ladder: 4 % more time, the cost of walking its instances.

## Limits

The node test is unchanged: reltol of the node's own voltage. With the same diode and resistor
between two 1 kV nodes, the run converges with 1.67 mV across the pair and 2.1 nA through the
resistor, against 0 exact. The diode's current is right, and the error sits in a linear element,
which has no test. 1.67 mV is 1.7e-6 of the node voltage, inside the tolerance the node test
defines.

A current into a low-impedance node is resolved only to `vntol` over the node's resistance. In
Family A's network 1168, a MOSFET's bulk junction carries 1.25 nA into a 65 Ω node, and the
reported node voltage is 82 nV short of the one that carries it, inside `vntol`. That was F1's
second face in the campaign; it is the tolerance's definition.
