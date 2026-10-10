# seedac_examples — Enhancements 832 to 835

F16–F19 of the
[2026-10-08 ngspice + OSDI hunt](../../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md):
an unseeded Verilog-A `$random`, a module's internal node with no DC path, the bins of one
model under `osdimc`, and an OSDI device's terminal current in `ac` and `sp`.

- **[1] [E-832](../../enhancements_doc/Enhancement-832.md) (F16).** `$random` and `$arandom`
  with no seed draw a new value in each analysis, and a different one in each instance.
  `setseed` reproduces the sequence. They drew the same number every time, in every
  instance. A seeded `$rdist_normal` still repeats (control). A draw holds one value through
  an analysis.
- **[2] [E-833](../../enhancements_doc/Enhancement-833.md) (F17).** An OSDI internal node
  reached only through `ddt()` gets the dc-path gmin at once, as its built-in twin does: 3
  iterations, where every homotopy used to fail (277). A transient releases it. A node with a
  resistive path is not named (control).
- **[3] [E-834](../../enhancements_doc/Enhancement-834.md) (F18).** Under `.option osdimc` the
  bins `nch.1` and `nch.2` move by one relative shift in every trial. They drew independently.
  Two unbinned cards still differ (control). `wcd` counts one dimension, and `highsigma`'s
  estimate matches a single card's.
- **[4] [E-835](../../enhancements_doc/Enhancement-835.md) (F19).** In `ac` and `sp`,
  `@n1[i_a]` is the device's small-signal current. It was the DC bias, real and flat. The
  checks: KCL against the source, `m=2`, an `ac_stim()` source, and `sp` against the port.
  `.options savecurrents` keeps these currents in `ac`. `op` is the control.

Run: `python3 verify_seedac.py` (20 checks per solver; 12 fail on the E-831 binaries).
