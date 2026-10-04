# vafslips_examples — Enhancements 791 to 795

The smaller slips D1 to D5 of the
[openvaf-r hunt of 2026-10-04](../../docs/bug_hunts/2026-10-04_openvaf-r-run-time-domains-filters-and-instances.md),
each pinned end-to-end through the committed openvaf-r, and through ngspice for the run-time
cases:

- **[1] [E-791](../../enhancements_doc/Enhancement-791.md) (D1).** A diagnostic quoted the
  whole source line it pointed into. A line longer than 240 bytes is now quoted as windows around
  each label, with the cuts marked `...`; the location keeps the line's real column.
- **[2] [E-792](../../enhancements_doc/Enhancement-792.md) (D2).** A real constant converted
  to an `integer` (`i = 1e20;`, a `repeat (1e10)` count) now draws L030. The run-time
  conversion and `$rtoi` give the same saturated value on every platform. On x86-64, 3e9 used
  to run as -1294967296.
- **[3] [E-793](../../enhancements_doc/Enhancement-793.md) (D3).** `%c` of 0 no longer cuts
  the line (with its line break), and `%b` of 0 prints `0`.
- **[4] [E-794](../../enhancements_doc/Enhancement-794.md) (D4).** `from [0:inf]` is lint
  L039 (`inclusive_infinite_bound`). It is allowed by default and enabled with
  `-W inclusive_infinite_bound`.
- **[5] [E-795](../../enhancements_doc/Enhancement-795.md) (D5).** `` `define include 7 ``
  (a directive's name as a macro name) is an error.

Run: `python3 verify_vafslips.py` (67 checks per solver, both solvers; 38 fail on the E-790
binaries).
