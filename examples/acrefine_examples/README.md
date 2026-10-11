# acrefine_examples — Enhancement-860

[E-860](../../enhancements_doc/Enhancement-860.md): F5 of the
[third robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

The ac factorization takes a pivot down to `pivrel` (1e-3) of its column's largest entry, and
Sparse orders the matrix at the first frequency only. On inductive networks at a few hertz that
cost up to 6 digits on matrices of condition 5: 22 of 300 networks under Sparse (3.4e-6), 5 under
KLU (2e-7), where any backward-stable solve gives 1e-15.

After each ac solve the residual now gives the componentwise backward error. Where that is
above rounding, one step of iterative refinement with the same factors restores the digits. A
point solved well is left as it was.

The networks are the campaign's worst (scratchpad `rc3/ac.py`, `AC_LOWF`), swept as the campaign
swept them. The reference is the exact complex MNA solve at each of ngspice's frequencies.

The checks:
- **[1]** Network 5025 (3.4e-6 under Sparse on E-859) to 1e-12.
- **[2]** Networks 5043, 5210 and 5049 to 1e-12.
- **[3]** Network 5035 (4.9e-8 under KLU on E-859) to 1e-12.
- **[4]** (control) A well-conditioned RLC ladder to 1e-13.

Run: `python3 verify_acrefine.py` (4 checks per solver; needs numpy). On the E-859 binaries [1],
[2] and [3] fail under Sparse, and [2] and [3] under KLU.
