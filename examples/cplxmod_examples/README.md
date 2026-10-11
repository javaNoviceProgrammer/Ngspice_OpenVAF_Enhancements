# cplxmod_examples — Enhancement-864

[E-864](../../enhancements_doc/Enhancement-864.md): F9 of the
[third robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

Complex `%` takes the real and imaginary parts modulo the divisor's (E-480), and checked that
both of the divisor's parts were nonzero. A real divisor promoted to complex has an imaginary
part of 0, so `v(1) % 2` after an ac failed "argument out of range for mod". A divisor with no
imaginary part now takes both parts modulo itself.

The checks:
- **[1]** After an ac, `v(1) % 2` evaluates, each part modulo 2.
- **[2]** (5.5 + 7.25j) % 2 is 1.5 + 1.25j, and % 0.3 part by part.
- **[3]** (control) A divisor of 0 is still refused.
- **[4]** (control) A complex divisor: part by part.
- **[5]** (control) Real % real.

Run: `python3 verify_cplxmod.py` (5 checks per solver). On the E-863 binaries [1] and [2] fail.
