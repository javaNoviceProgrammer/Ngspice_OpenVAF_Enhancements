# Enhancement-64 — Touchstone export: auto-`Rbase`, N-port `wrsnp`, 1-port `.sp` (version11)

This document describes Enhancement-64: making S-parameter results
exportable to industry-standard Touchstone v1 files from the `.sp`
analysis. Follows directly from Enhancement-63's findings. ngspice-only —
no compiler/OSDI change.

## What was broken

1. **`wrs2p` was unusable out of the box.** It required a vector named
   `Rbase` (the reference resistance for the Touchstone option line
   `# Hz S RI R <Rbase>`) that **no code ever created** — every call died
   with `Error: No Rbase vector given` unless the user knew the
   undocumented `let Rbase = 50` incantation, and a wrong value silently
   mislabeled the file header. The reference impedance is *already known*
   from the ports' `z0`.
2. **2 ports only**, though the `.sp` analysis itself is fully N-port
   (Enhancement-63 verified 3-/4-port S-matrices analytically exact).
3. **1-port `.sp` was rejected outright** ("we need at least two!") — and
   the check was hiding a real crash: with it lifted, ngspice died with
   `malloc: can't allocate -8 bytes`.

## The fixes

### Auto-`Rbase` (`span.c`, `cktspdum.c`, `postcoms.c`)

The `.sp` analysis now **publishes `Rbase`** as a vector in its plot —
one more UID after the Z-matrix block, with the per-point value read
straight from port 1's `VSRCportZ0` (the `refPortY0` global is only set
on the noise path, so it is not used). `com_write_sparam` reads it
robustly (the sp plot is complex data; the old code blind-dereferenced
`v_realdata[0]`) and a user-defined `let Rbase = …` still overrides.

### N-port writer + `wrsnp` (`postcoms.c`, `commands.c`)

New `spar_write_np()` writes Touchstone v1 for **any port count** directly
from the `S_i_j` vectors: `# Hz S RI R <Rbase>` option line; for N ≥ 3 the
matrix is **row-major with at most four complex pairs per data line and
every matrix row starting on a new line** (per the Touchstone 1.x spec);
a 1-port is one pair per line. The port count is auto-detected by probing
`S_n_n` vectors. The classic 2-port `S11 S21 S12 S22` column order is
preserved through the original `spar_write()` path. A new **`wrsnp`**
command is registered; `wrs2p` transparently dispatches to the N-port
writer when the plot isn't 2-port.

### 1-port `.sp` (`span.c`, `maths/dense/dense.c`)

The "at least two ports" hard error was over-strict — a 1-port `.sp` is a
plain reflection measurement and the matrix machinery is N-general. The
real bug it hid: the complex-matrix **`cadjoint()` had no 1×1 base case**,
so its cofactor loop allocated 0×0 and then negative-sized minors
(`cdet` had the base case; `cadjoint` didn't). The adjugate of `[a]` is
`[1]` (the empty minor's determinant is 1 by convention), which makes
`cinverse` of a 1×1 equal `1/a`. With both fixed, a 100 Ω load on a 50 Ω
port gives S11 = 1/3 exactly in a proper `.s1p`.

## Examples (`touchstone_examples/`, 11 checks, ALL PASS)

`verify_touchstone.py`: [1] `wrs2p` with **no** manual `Rbase` (header
`R 50`; the file's S21 pairs equal the plot's `S_2_1` — also pins the
2-port column order); [1b] `wrsnp` on a 2-port produces a byte-identical
file to `wrs2p` (same handler — both commands cover every port count);
[2] `let Rbase = 75` override honored; [3] 1-port
`.s1p`, S11 = 1/3 exactly (pins the `cadjoint` crash fix); [4] `.s3p` —
3 frequency blocks × 9 pairs of exactly 1/3 with each matrix row on its
own line; [5] `.s5p` — 25 pairs of exactly 1/5 with rows wrapping at 4
pairs per line.

## Notes

- Found while testing: `.sp lin 2 fstart fstop` produces only **one**
  frequency point in stock ngspice (`lin 3`/`lin 5` behave); worked
  around in the suite with `lin 3`, not fixed (separate stock quirk).
- All values written are from OSDI (Verilog-A) resistor networks with
  analytically known S-matrices — the star topologies from
  Enhancement-63's N-port verification.

## Regression

All version11 example verify suites pass with the rebuilt ngspice; no
compiler change.
