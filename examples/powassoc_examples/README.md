# powassoc_examples — Enhancement-865

[E-865](../../enhancements_doc/Enhancement-865.md): F10 of the
[third robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

The manual says equal-precedence binary operators evaluate left to right. The `.param`, the
B-source and Verilog-A's LRM take 2^3^2 as (2^3)^2 = 64; `let` gave 512. `'^'` now associates
left to right in `let` too.

Unary minus sits below `^` in all three of ngspice's parsers (−2^2 is −4), where the manual's
precedence table lists it above.

The checks, each expression through a `.param`, a B-source and `let`:
- **[1]** `let` 2^3^2 is 64.
- **[2]** 2^0.5^2, 2^2^3, 3^2^0.5: the three agree to the bit.
- **[3]** (control) 2^-3^2 is 2⁻⁹ in all three.
- **[4]** (control) −2^2 is −4 in all three.
- **[5]** (control) The `.param`'s `**` and `^` chains.

Run: `python3 verify_powassoc.py` (5 checks per solver). On the E-863 binaries [1] and [2] fail.
