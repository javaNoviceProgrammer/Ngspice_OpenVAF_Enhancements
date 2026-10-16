# Enhancement-893: wrdata writes a vector longer than its scale in full — `let g = vector(1000)` then `wrdata` wrote one row, without a word

**Scope:** D2 of the
[nonlinear correctness campaign of 2026-10-15](../docs/bug_hunts/2026-10-15_ngspice-openvaf-r-nonlinear-correctness-campaign.md).

ngspice: `frontend/plotting/gnuplot.c` (`ft_writesimple`). A vector longer than its scale is
written in full, its index in the scale's column, with a note.

`examples/nlnotes_examples/` [4] to [6], shared with [E-892](Enhancement-892.md) and
[E-894](Enhancement-894.md). **ngspice only.**

**Suites:**
- [`nlnotes_examples`](../examples/nlnotes_examples/): [4] to [6] are this enhancement's. On the
  E-888 binaries [4] and [5] fail; [6] is a control.
- The full sweep: 591 of 591.

## What was wrong

`wrdata` writes each vector beside its scale, and it wrote as many rows as the longest scale. A
vector longer than its scale was cut to the scale's length. In the constants plot, or after an
`op`, the scale has one point, so this wrote one row of a 1000-point vector:

```
let g = vector(1000)
wrdata wg.txt g
```

It said nothing. With `wr_singlescale` set, it refused instead, with a message that named the
vector twice: "Vectors g and g have different lengths!"

## The change

A vector longer than its scale is written in full, with its index in the scale's column, under an
`index` header when `wr_vecnames` or `wr_csv` asks for names. A note says so:

```
Note: g has 1000 points and its scale 'yes' has 1: the index is written in the scale's column.
```

`wr_singlescale` measures such a vector by its own length, so it writes it. Vectors no longer than
their scale are written as before.

## The checks

`nlnotes_examples`:
- **[4]** A 1000-point vector in the constants plot writes 1000 rows, its last row `999 999`,
  with the note. E-888: one row.
- **[5]** After an `op`, with `wr_singlescale` and `wr_vecnames`: 1000 rows under an `index`
  header. E-888: refused.
- **[6]** (control) A transient's vector writes its own rows and no note.
