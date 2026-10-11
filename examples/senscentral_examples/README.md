# senscentral_examples — Enhancement-861

[E-861](../../enhancements_doc/Enhancement-861.md): F6 of the
[third robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

`sens` divided the change in a device's stamp at p + δ, δ = 1e-6 of p, by δ: a one-sided
difference. A gain or a source enters the stamp linearly and came out exact. A resistance
enters as 1/R, and every sensitivity to one was low by exactly the factor 1/(1 + 1e-6).

The step is now central, p + δ against p − δ over 2δ, where the parameter is not zero, with the
same number of loads.

The checks:
- **[1]** dV(4)/dR1..dR4 of a resistive network with a VCVS, to 1e-9 of the analytic values.
- **[2]** An ac sensitivity, dH/dR of an RC low-pass at three frequencies, to 1e-9.
- **[3]** A diode's `rs`, against a central difference of two tight operating points, to 1e-7.
- **[4]** (control) The VCVS's gain.
- **[5]** (control) A diode's `is`.

Run: `python3 verify_senscentral.py` (5 checks per solver). On the E-859 binaries [1], [2] and
[3] fail.
