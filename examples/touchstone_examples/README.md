# touchstone_examples — Touchstone export from `.sp` (Enhancement-64)

Writing S-parameter results to industry-standard Touchstone v1 files
(`.s1p`/`.s2p`/`.sNp`) — the follow-up to Enhancement-63's finding that
`wrs2p` was unusable out of the box and hardwired to two ports.

## What was broken

1. `wrs2p` demanded a vector named `Rbase` (the reference resistance for
   the `# Hz S RI R <Rbase>` option line) that **nothing ever created** —
   every call failed with `Error: No Rbase vector given` unless the user
   knew to type `let Rbase = 50` first (and could silently mislabel the
   file by typing the wrong value).
2. It was hardwired to exactly 2 ports (`S_1_1 … S_2_2`), though the `.sp`
   analysis itself is fully N-port.
3. A **1-port** `.sp` (a plain reflection measurement) was a hard error —
   and after lifting that over-strict check, ngspice *crashed* with
   `malloc: can't allocate -8 bytes`: the complex-matrix `cadjoint()` had
   no 1×1 base case, so its cofactor loop allocated negative-sized minors.

## What now works

- **Auto-`Rbase`**: the `.sp` analysis publishes `Rbase` into its plot
  (read from port 1's `z0`), so `wrs2p`/`wrsnp` work with no manual step.
  A user-defined `let Rbase = …` still overrides.
- **`wrsnp <file>`** (new command; `wrs2p` dispatches to it for N ≠ 2):
  Touchstone v1 for **any port count**. N ≥ 3 uses the spec's row-major
  layout — at most four complex pairs per data line, each matrix row
  starting on a new line; a 1-port is one pair per line. The classic 2-port
  `S11 S21 S12 S22` column order is preserved via the original writer.
- **1-port `.sp`** analyses run (the adjugate of `[a]` is `[1]`, making
  `cinverse` of a 1×1 equal `1/a` — fixed in `maths/dense/dense.c`).

## Round 2 (Enhancement-72)

`wrsnp` gained output options — `wrsnp <file> [ri|ma|db] [s|y|z]
[hz|khz|mhz|ghz]` (MA = magnitude/angle-degrees, DB = 20·log₁₀/angle;
Y/Z exported **normalized to Rbase** per the Touchstone v1 spec; the
option line reflects every choice) — and a **reader**:
`rdsnp <file> [nports]` loads any Touchstone v1 file into a new plot
with a Hz `frequency` scale and complex vectors matching the `.sp`
plot's conventions (MA/DB converted back, Y/Z de-normalized, 2-port
column order handled), so measured data compares 1:1 against simulated
vectors. The suite pins a full write-MA → read → compare round-trip at
4e-8 and a hand-written measurement-style file read back exactly.

## Run

```bash
python3 verify_touchstone.py    # 24 checks
```

[1] `wrs2p` with no manual `Rbase` — header `R 50`, file S21 pairs equal
the plot's `S_2_1`; [2] `let Rbase = 75` override honored; [3] 1-port
`.s1p` with S11 = 1/3 exactly (pins the crash fix); [4] `.s3p` — 3
frequency blocks × 9 pairs, all 1/3, each matrix row on its own line;
[5] `.s5p` — 25 pairs of 1/5, rows wrapping at 4 pairs per line.

## Round 3 (Enhancement-744) — `rdsnp` reads Touchstone 2

The reader scanned data lines with `sscanf`, which stops at a `[`, so every
Touchstone 2 keyword line was dropped whole: `[Two-Port Data Order] 12_21`
was never seen and S12/S21 came back swapped, `[Reference]` was lost, and a
v2 Y/Z file would have been de-normalized as v1. Now the keywords are read —
a per-port `[Reference]` (continued over lines) is published as the vector
`Zref` with `Rbase` port 1's, `[Matrix Format] Lower`/`Upper` is mirrored,
an information block and a `[Noise Data]` section are skipped — and
`[Mixed-Mode Order]`, the G/H types, an unknown keyword, a two-port without
its data order and a port count that disagrees with the command or the
extension are refused by name. A count that is not a whole number of frames
names the count and the v1 noise-parameter rows as the usual cause (it said
"wrong port count?"), a v2 Y/Z file is absolute and a v1 one de-normalized,
the port count comes from a `.yNp`/`.zNp` extension too, and a file with no
option line takes the specification's default `GHz S MA R 50` (the reader
assumed `Hz S RI`). Section [9]: seven checks on hand-written files, each
of these pinned.
