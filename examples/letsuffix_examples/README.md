# letsuffix_examples — Enhancement-859

[E-859](../../enhancements_doc/Enhancement-859.md): F4 of the
[third robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

`ft_numparse`, the front end's number reader, took a scale factor or an exponent, never both:
`let x = 1.5e2u` was 150 where an element value 1.5e2u is 1.5e-4, `1e3meg` was 1000 and
`1e-3k` 0.001, without a word. It now reads the exponent and then the scale factor into one
exact decimal, so the value is the netlist's to the bit.

The checks:
- **[1]** `let x = 1.5e2u` is 1.5e-4.
- **[2]** 1e3meg, 1e-3k, 4.7e3p, 2.2e-1u, 3.3e2mil.
- **[3]** 300 spellings with an exponent and a suffix: `let` is the element value to the bit.
- **[4]** Inside an expression: `v(1) * 1e-3k` and `2e1u + 0`.
- **[5]** (control) An `e` that is not an exponent is trailing text: `1em` is 1, `2ex` is 2.
- **[6]** (control) Plain numbers and suffixes.

Run: `python3 verify_letsuffix.py` (6 checks per solver). On the E-857 binaries [1]–[4] fail.
