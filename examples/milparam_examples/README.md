# milparam_examples — Enhancement-858

[E-858](../../enhancements_doc/Enhancement-858.md): F3 of the
[third robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

numparam's suffix table had no `mil`. It read `m` and let "il" go, so `{1mil}` was 1e-3, where
`r1 1 0 1mil`, a B-source and `let` give 25.4e-6, the manual's value.

The dig found two more drifts from the netlist's reading of the same text:
- A mantissa with its own exponent was multiplied by the suffix, a second rounding:
  `{66.5e4u}` was an ulp off.
- The value went back into the deck with 16 significant digits: `{0.1+0.2}` reached the
  element as 0.3.

`mil` is now 25.4e-6. The exponent and the suffix are folded into one exact decimal, and the
value goes back with 17 digits, so a `.param` is the double the netlist reads.

The checks:
- **[1]** `{1mil}` is `1mil` to the bit.
- **[2]** `mil`'s spellings: 2.5mil, 1MIL, 10mils, 3.3e2mil, 1e-3mil.
- **[3]** `mil` in an expression, and through a subcircuit parameter.
- **[4]** 300 spellings with an exponent and a suffix: each `.param` is the element value to
  the bit.
- **[5]** 17 digits reach the element: `{0.1+0.2}`, and `{sin(45f/7.1f)}` as the B-source.
- **[6]** (control) Plain suffixes, and `m` still milli.

Run: `python3 verify_milparam.py` (6 checks per solver). On the E-857 binaries all but the
control [6] fail.
