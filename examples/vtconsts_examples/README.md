# vtconsts_examples — Enhancement-862

[E-862](../../enhancements_doc/Enhancement-862.md): F7 of the
[third robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

openvaf-r's `$vt` took the 2019 exact SI values whatever the model included. The shipped
`constants.vams` defaults `P_K` and `P_Q` to NIST 1998 ([E-519](../../enhancements_doc/Enhancement-519.md)),
so inside one model `$vt(T)` sat 1.05e-6 below `` `P_K*T/`P_Q ``.

`$vt` now uses the model's `P_K` and `P_Q` when it defines both: the header's default, any of its
branches, or the model's own. It computes them in the order `` `P_K*T/`P_Q `` evaluates in, so the
two agree to the bit. A model that names no constants keeps the 2019 values.

The checks:
- **[1]** The default header: `$vt(300.15)` is `` `P_K*300.15/`P_Q `` to the bit.
- **[2]** (control) With `PHYSICAL_CONSTANTS_NIST2018`: the same, at the 2019 values.
- **[3]** `$vt` without an argument and `` `P_K*$temperature/`P_Q ``, at 27 °C and 85 °C.
- **[4]** A model's own `P_K` and `P_Q`, ngspice's CODATA 2014 pair: `$vt` is ngspice's
  `boltz*T/echarge`.
- **[5]** (control) No constants named: `$vt` is the 2019 SI kT/q, as before.

Run: `python3 verify_vtconsts.py` (5 checks per solver). On the E-861 binaries [1], [3] and [4]
fail.
