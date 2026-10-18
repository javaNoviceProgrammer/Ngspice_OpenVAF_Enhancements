# txlcpl_examples — Enhancements 904 to 908

The KSPICE lossy lines, TXL (`Y`) and CPL (`P`): F9 of the
[analyses correctness campaign of 2026-10-16](../../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md).
The references are the exact line, the telegrapher's two-port, and the circuit's own operating
point.

[E-904](../../enhancements_doc/Enhancement-904.md), the transient starts from the operating
point:
- **[1]** A TXL carrying dc current holds its operating point under a constant source.
- **[2]** The same for a CPL line.

[E-905](../../enhancements_doc/Enhancement-905.md), the characteristic admittance's history:
- **[3]** A TXL driven above its RC corner R/L: the fundamental within 1e-5 of the exact line.

[E-906](../../enhancements_doc/Enhancement-906.md), exact convolution steps:
- **[4]** A lossy TXL driven in its RC regime stays periodic, within 2 % of the exact line, for
  3 ms.

[E-907](../../enhancements_doc/Enhancement-907.md), 64-bit time:
- **[5]** A TXL keeps following its source past 2.147 ms.
- **[6]** The same for a CPL line.

[E-908](../../enhancements_doc/Enhancement-908.md), the lines say where they hold:
- **[7]** A lossy TXL, a TXL that drops its resistance, a TXL model simulated as CPL, and a lossy
  CPL each print a Note.

Run: `python3 verify_txlcpl.py` (7 checks per solver, about 15 s each). On the E-903 binaries all
7 fail.
