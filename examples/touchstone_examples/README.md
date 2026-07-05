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

## Run

```bash
python3 verify_touchstone.py    # 11 checks
```

[1] `wrs2p` with no manual `Rbase` — header `R 50`, file S21 pairs equal
the plot's `S_2_1`; [2] `let Rbase = 75` override honored; [3] 1-port
`.s1p` with S11 = 1/3 exactly (pins the crash fix); [4] `.s3p` — 3
frequency blocks × 9 pairs, all 1/3, each matrix row on its own line;
[5] `.s5p` — 25 pairs of 1/5, rows wrapping at 4 pairs per line.
