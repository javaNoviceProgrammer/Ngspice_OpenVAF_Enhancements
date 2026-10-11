# guardgain_examples — Enhancement-869

[E-869](../../enhancements_doc/Enhancement-869.md): N1 of the
[Sparse and KLU correctness campaign of 2026-10-11](../../docs/bug_hunts/2026-10-11_sparse-klu-correctness-campaign.md).

An inverting amplifier built from a VCVS of open-loop gain 1e12 went through 126 iterations of
dynamic gmin stepping under KLU, where a gain of 1e11 took 3. The answer was right; E-256's
false-convergence guard declined it. The control voltage of the VCVS is v(out)/A, rounded at the
circuit's volts, and the gain multiplies that rounding into its branch row: 2.5e-5 of residual in
2.5 of terms. The guard exempted a row only below one part per million of its terms.

The guard now also allows 1024 ε of (|G|s)ₖ, where sⱼ is the largest unknown of j's kind. That
is the line below which E-868's refinement takes a row for rounding. A real KCL violation sits
many decades above it.

The checks:
- **[1]** The inverter at gains 1e12, 1e13 and 1e15: exact, in at most 5 iterations.
- **[2]** Its transient at a gain of 1e12: exact.
- **[3]** A dc sweep of the gain from 1e12 to 1e15: exact at every point, in at most 25
  iterations.
- **[4]** (control) A gain of 1e9: 3 iterations, as before.
- **[5]** (control) The guard still declines E-256's false point. `B I=sqrt(v(n))` on a
  0.6 V / 1 Ω divider reaches v(n) = 0.17805 V, not 0.

Run: `python3 verify_guardgain.py` (5 checks per solver). On the E-867 binaries [1] and [3] fail
under KLU (126 and 235 iterations); under Sparse all pass.
