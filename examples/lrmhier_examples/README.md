# lrmhier — hierarchy vs. the LRM (Enhancement-525)

An LRM-2023 conformance audit of clause **6** found five silent
hierarchy bugs. This suite pins the fixes end-to-end:

- **`defparam` survives generate** (6.3.1): any module containing a
  generate construct silently dropped *every* defparam (module-scope
  or inside blocks — the generate-block parser had no defparam arm and
  the re-render swallowed the parse error). Pinned: defparam inside
  `generate for` (per-iteration targets, genvars in the value), inside
  `generate if`, at module scope beside a generate, and its LRM
  precedence over `#(...)` two levels down.
- **`#(.$mfactor(4))` / `.$xposition(...)` child overrides work**
  (6.3.6): they compiled clean and did nothing. The full multiplicity
  transform now applies — reads compose (× for `$mfactor`, + for
  positions), flow contributions scale ×m, flow probes read per-copy,
  noise power scales ×m — verified numerically including netlist `m=`
  composition, nested ×2-under-×4 = ×8, and the noise-amplitude √4
  ratio. Duplicate and unknown `.$` overrides are targeted errors.
- **`$param_given` sees hierarchy overrides** (6.3.5/9.19): flattening
  baked an instance `#(...)` value in as the new default, so
  `$param_given` reported *not given*; both the given and not-given
  siblings are pinned.
- **Connection sizes are checked** (6.5.7.1): a scalar net on a 2-bit
  port was silently replicated onto both bits; it errors citing the
  clause, while `{p,q}` concatenations still connect bit-per-bit
  (−5 V computed).
- **Mixed positional+named parameter overrides error** (Syntax 6-2):
  the positional half used to be silently dropped.

Run `python3 verify_lrmhier.py` — 22 checks, both solvers.
