# Enhancement-898: a built-in HICUM pnp simulates — with nothing but c10 and qp0 it ran to NaN, and none of 150 random pnp cards solved

**Scope:** found while digging into F2 of the
[analyses correctness campaign of 2026-10-16](../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md)
([E-896](Enhancement-896.md)). No example in ngspice uses a built-in HICUM pnp, and the
regression suites had none.

ngspice:
- `spicelib/devices/hicum2/hicumL2.cpp`: the branch voltages and currents keep the device's own
  polarity; the type is applied where a row or column crosses between a circuit node and the
  thermal or NQS nodes.
- `spicelib/devices/hicum2/hicum2acld.c`, `hicum2pzld.c`: the same crossing rule.
- `spicelib/devices/hicum2/hicum2conv.c`: the thermal node is read as it is.

**ngspice only.**

**Suites:**
- [`hicum2_examples`](../examples/hicum2_examples/): checks [9] to [11]. 16 of 16 per solver;
  on the E-895 binaries 15 of 16 fail.
- The full sweep: 592 of 592.

## What was wrong

The model works in the device's own polarity: Vbiei = type·(V(bi) − V(ei)), positive for a
forward-biased junction of either type, and currents in the same sense. The stamps turn them
back into node quantities. For an npn (type = 1) every one of these steps is the identity, so
only a pnp saw them, and four steps applied the type wrongly:
- **The voltages, twice.** Every path that forms the branch voltages already applies the type,
  or takes them from the state vector, which holds them so. Before the model was evaluated, a
  block multiplied them by the type again. A pnp's forward bias read as reverse; the junction
  start `tVcrit` became −0.97 V; and `ac` reversed the stored bias the same way. Only the
  `uic` path had pre-multiplied its initial conditions by the type, "for historical reasons",
  to be undone there.
- **The branch currents, twice.** `Ibiei`, `Ibpei`, `Ibici`, `Iciei`, `Ibpci`, `Isici` and
  `Ibpsi` and their derivatives were stored as type·i. The stamps multiply by the type again, as
  they do for the charge currents added to these branches and for `Ibpbi`. `HICUMask` and the
  noise also take them unsigned. A pnp's junction conductances and currents were negated.
- **The thermal and NQS nodes, never.** Where a circuit node's row meets the thermal or an NQS
  node's column, or the reverse, the entry needs the type once. The temperature and the NQS
  quantities are not mirrored. None had it.
- **The convergence test** read the thermal node as type·V(T), so a pnp with self-heating never
  converged.

A pnp with `c10` and `qp0` alone went to NaN in its first iterations. Of 150 random cards, the
pnp mirror of the npn circuit solved none.

## The change

- The second application of the type to the voltages is gone, and the `uic` path takes
  `icvbe`, `icvce` and `icvcs` as they are, positive for either type.
- The branch currents and their derivatives are in the device's polarity, and the stamps apply
  the type.
- Every stamp whose row and column are of different kinds, a circuit node and the thermal or an
  NQS node, is multiplied by the type. In `hicumL2.cpp` that is 58 entries and the 11
  self-heating rhs terms; in `hicum2acld.c` 82; in `hicum2pzld.c` 106. The rule is mechanical,
  from the pointer names.
- `hicum2conv.c` reads Vrth as V(T). The power derivatives of `flsh=2` take `ijbcx` and `ijsc`,
  as the power itself does, not the signed `Ibpci` and `Isici`.

For an npn every change is a multiplication by 1.

## The checks

`hicum2_examples`:
- **[9]** A pnp with `c10` and `qp0` solves, the mirror of the npn to 1e-12. E-895: no
  operating point.
- **[10]** Two cards rich in effects (avalanche, NQS, lateral spreading, rbi, the substrate
  transistor, self-heating at `flsh` 1 and 2, rbx, re, rcx): the pnp mirror's `op`, `ac`, noise
  and transient equal the npn's to 1e-9. E-895: no operating point.
- **[11]** The pnp within 1e-4 of the Verilog-A model's pnp. E-895: none.

60 random cards, npn against the pnp mirror with every source negated:
- The operating points agree to 3.8e-15.
- `ac` from 1 Hz to 10 GHz, the output noise and a 2 µs transient are identical.
- The pnp cards against the Verilog-A model's pnp: 149 of 150 solve, as for the npn, with the
  npn's statistics. E-895: 0 of 150.
