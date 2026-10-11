# lettan_examples — Enhancement-863

[E-863](../../enhancements_doc/Enhancement-863.md): F8 of the
[third robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

`d_tan`, the front end's real tangent, checked `tan(x) != 0`, which refused a valid result:
`let x = tan(0)` failed "argument out of range for tan" while `tan(0.5)` was fine, and `tan(0)` is
0 in a `.param` and a B-source. The check is now that the result is finite.

The checks:
- **[1]** `let a = tan(0)` is 0.
- **[2]** A vector with a 0 in it: tan of each element.
- **[3]** With `units=degrees`: tan(0) is 0, tan(45) is 1 to rounding.
- **[4]** (control) `tan(0.5)`, `tan(-0.5)` and a complex `tan(0)`.
- **[5]** (control) The `.param` and the B-source give 0 for `tan(0)`.

Run: `python3 verify_lettan.py` (5 checks per solver). On the E-861 binaries [1], [2] and [3]
fail.
