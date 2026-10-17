# hicum2_examples — Enhancements 896 to 899

The built-in HICUM L2.4.0 (`level=8`): F2 of the
[analyses correctness campaign of 2026-10-16](../../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md),
and what digging into it found. No suite exercised the built-in HICUM before.

The small-signal checks compare `ac` at 1 Hz with the central difference of a three-point `dc`
sweep: the derivative of the operating point, which the Jacobian has to reproduce. The value
checks compare with the corpus's own Verilog-A HICUM L2.4.0 (`hicumL2V2p4p0.va`), compiled by
the suite.

[E-896](../../enhancements_doc/Enhancement-896.md), the Jacobian:
- **[1]** `t0` = 0, its default: `ac` within 1e-6 of the dc derivative.
- **[2]** `rbi0` > 0.
- **[3]** Tunnelling, with the b-e junction at −2 V.
- **[4]** Self-heating with `rcx` and `zetarcx` under KLU, and equal to Sparse's `ac`.
- **[5]** SOI3 with `rt` under KLU: `ac` equal to Sparse's, no stale binding.
- **[6]** No device's KLU binding names a matrix pointer twice (a scan of the source tree).

[E-897](../../enhancements_doc/Enhancement-897.md), values:
- **[7]** `latb`, `latl` and `vcbar` at high current: the collector current within 1e-4 of the
  Verilog-A model.
- **[8]** The substrate transistor in saturation at the default `flcomp`: its current within
  1e-3 of the Verilog-A model.

[E-898](../../enhancements_doc/Enhancement-898.md), pnp:
- **[9]** A pnp with `c10` and `qp0` solves, the mirror of the npn.
- **[10]** Two cards rich in effects: the pnp mirror's `op`, `ac`, noise and transient equal
  the npn's to 1e-9.
- **[11]** The pnp within 1e-4 of the Verilog-A model's pnp.

[E-899](../../enhancements_doc/Enhancement-899.md), self-heating robustness:
- **[12]** Two analyses on a three-node circuit with an internal thermal node.
- **[13]** Two analyses with the thermal terminal on a node numbered past 6.
- **[14]** `flsh=2` with `re` solves, within 1e-4 of the Verilog-A model.
- **[15]** Self-heating at −120 °C: within 1e-4 of the Verilog-A model, no NaN.
- **[16]** `ibeis` 1e4 below c10/qp0 solves in at most 11 iterations.

Run: `python3 verify_hicum2.py` (16 checks per solver). On the E-895 binaries 15 fail; [6] scans
the source tree and passes on any binary.
