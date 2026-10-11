# Enhancement-871: with `pivrel=1` Sparse no longer reports a pivot above `pivtol` as below it — "the pivot … is 1e+12, below pivtol (1e-13)"

**Scope:** D1 of the
[Sparse and KLU correctness campaign of 2026-10-11](../docs/bug_hunts/2026-10-11_sparse-klu-correctness-campaign.md).

ngspice: `maths/sparse/spfactor.c`, `SearchEntireMatrix`.

`examples/pivrelone_examples/` (new). **ngspice only.**

**Suites:**
- [`pivrelone_examples`](../examples/pivrelone_examples/): 4 of 4 per pass. On the E-869
  binaries [1] and [2] fail; [3] and [4] are controls.
- `solvercore`, whose E-736 checks report a pivot below `pivtol`, passes.
- The full sweep: see [Enhancement-872](Enhancement-872.md), folded with it.

## What was wrong

`SearchEntireMatrix`, Sparse's last pivot search, accepts an element only if
`Magnitude > RelThreshold * LargestInCol`. With `pivrel=1` that strict test admits nothing, so
every search that reaches it falls through to the largest element of the reduced matrix.
[Enhancement-736](Enhancement-736.md) took that fallback for the one where no element is above
`pivtol`, and recorded each such pivot as small. With `pivtol` set, a follower of gain 1e12
reported:

```
Warning: the pivot for node neg (from the equation of node e1#branch) is 1e+12, below pivtol (1e-13)
```

A teraohm network reported 3370.9 and 1. Only the first small pivot of an ordering is recorded,
so the false one also hid a pivot that was below `pivtol`: 3.2e-14.

## The change

The fallback is a small pivot only when the largest element is at or below the absolute
threshold. Only then does it set `spSMALL_PIVOT` and E-736's record. A fallback that `pivrel=1`
caused returns its pivot as an ordinary one. The pivot chosen is the same, so every answer is
unchanged to the bit.

The follower now reports nothing. The teraohm network reports its 3.2e-14, which is below
`pivtol`.

## The checks

`pivrelone_examples` (the decks pin Sparse, whose search this is):
- **[1]** A follower, `pivrel=1 pivtol=1e-13`: no pivot is reported.
- **[2]** Teraohm dead ends, `pivrel=1 pivtol=1e-13`: every pivot reported is below 1e-13.
- **[3]** (control) A pivot below `pivtol` is still reported: the follower with `pivtol=1e13`.
- **[4]** (control) The answers are unchanged: the follower's to the bit, and v(3) = v(1).
