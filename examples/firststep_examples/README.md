# firststep_examples — Enhancements 846 and 847

[E-846](../../enhancements_doc/Enhancement-846.md) and [E-847](../../enhancements_doc/Enhancement-847.md):
F2 and F3 of the
[second robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

The first transient step was accepted without a truncation check. It is a fixed fraction of the
run, 1 ns for `tran 1u 10u`, whatever the time constants and tolerances. A sine into a 1 ns RC
was 32 % off at its first point at `reltol=1e-7`, and a `uic` charge 21 %. The bad point then
stayed in every later estimate, and a 7-element linear L–C network collapsed with "Timestep too
small" at `reltol` ≤ 1e-6. After an operating point the circuit was at rest before t = 0, which
is the history the check needs, and it is now made. And an inductor's error floor was `abstol`,
a current, applied to the voltage across it: with a small `chgtol` the network still collapsed
under KLU at `reltol=1e-7`. The floor is now `vntol` (E-847).

The checks:
- **[1]** A sine into a 1 ns RC from the op at `reltol=1e-7`: the first sample, and the whole
  run, against the exact solution.
- **[2]** A 1 ns RC charged from `.ic v(1)=0` under `uic`: the first step's sample, index 1
  since [E-852](../../enhancements_doc/Enhancement-852.md) wrote the t = 0 point.
- **[3]** The reduced L–C network at `reltol` 1e-6, 1e-7, and 1e-7 with `chgtol=1e-20`, and at
  the defaults (control): each runs to tstop.
- **[4]** (control) An `.ic` that a source contradicts still runs.
- **[5]** (control) An RC step response at the default tolerances, against the exact value.

Run: `python3 verify_firststep.py` (9 checks per solver). On the E-844 binaries the 6 checks of
the defect fail.
