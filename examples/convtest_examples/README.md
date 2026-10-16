# convtest_examples — Enhancement-889

[E-889](../../enhancements_doc/Enhancement-889.md): F1 of the
[nonlinear correctness campaign of 2026-10-15](../../docs/bug_hunts/2026-10-15_ngspice-openvaf-r-nonlinear-correctness-campaign.md).

Every built-in device's convergence test ran and was ignored, most read the point they had been
loaded at, and a Verilog-A device had none. An operating point was accepted as soon as no node moved
more than reltol of its voltage in a step: 0.1 V at 100 V. The device tests now decide, on the new
solution, and a Verilog-A device has one.

The checks:
- **[1]** A diode across a 794 kΩ resistor, both between two 100 V nodes, converges off.
- **[2]** The same with a Verilog-A diode (`ctdio.va`).
- **[3]** The same with a Verilog-A diode behind a series resistance on an internal node
  (`ctdiors.va`).
- **[4]** An npn's base across the resistor converges off.
- **[5]** A level-1 MOSFET's bulk junction, started forward by a nodeset, converges off.
- **[6]** A `dc temp` sweep of a diode at default tolerances is within 30 µV of the same sweep at
  `reltol=1e-9` at every point.
- **[7]** An npn that an ideal source forward-biases by 2 V converges: steps at the rounding of the
  unknowns are not steps.
- **[8]** A diode marked `off` that the circuit drives forward converges in at most 20 iterations,
  within reltol of the point it reaches without `off`.
- **[9]** A closed Verilog-A switch between two 100 V nodes (`ctsw.va`) converges in at most 10
  iterations.

Run: `python3 verify_convtest.py` (9 checks per solver). On the E-888 binaries [1] to [6] and [8]
fail.
