# Enhancement-735: Sparse's ordering is no longer quadratic in the node count — the pivot search kept its element lists sorted by internal row and column and moved elements through them at every interchange and every fill-in, so a 300 × 300 resistor mesh spent 213 s of a 226 s run reordering under Sparse where KLU took 1.8 s; the lists now stay in a layout the ordering never has to walk through, the Markowitz scan is a bucket index, the same pivots are chosen and the same factors come out, and the mesh reorders in 9 s

**Scope:** N1 of the
[second KLU/Sparse solver-core hunt of 2026-09-25](../docs/bug_hunts/2026-09-25_klu-sparse-solver-cores-second-hunt.md).
**ngspice only, Sparse 1.3 only** (`.option sparse`; KLU, the default solver, is untouched).
`src/maths/sparse/spfactor.c` (the ordering loop of `spOrderAndFactor`, the searches, the
new `Order*` routines), `spbuild.c` (`spcCreateFillin`), `spdefs.h` (ordering fields of
the matrix frame), `spalloc.c` (their lifetime).
[`examples/solvercore_examples/`](../examples/solvercore_examples/) (section [N1], 8 checks,
27 per solver). Handbook [§3.7](../docs/handbook/03-ngspice-workflows.md). The hunt page.

**Suites:** `solvercore` 27 of 27 per solver, both solvers (26 of 27 under Sparse on the
E-734 binaries: the mesh's reorder time; 26 of 26 under KLU); `oprobust` 38 of 38,
`floatnode` 16 of 16, `singularname` 12 of 12, `acgminhold` 10 of 10, `internalnode` 28 of
28, `dcpath` per solver, both solvers, unchanged; no new build warnings; full sweep, run
alone. Beyond the suites: a standalone driver factors 86 matrices with the old and the new
`spfactor.c` and diffs everything the ordering decides (see Verification); the 122 Sparse
decks of the hunt's harnesses print the same numbers on both binaries.

## What was wrong

```spice
* a 300 x 300 resistor mesh (90 001 nodes), one corner driven, the other loaded
.option sparse
V1 n0_0x 0 1
R0 n0_0x n0_0 1
R1 n0_0 n0_1 1k
R2 n0_0 n1_0 1k
* ... 179 400 resistors ...
Rl n299_299 0 1k
.control
op
print v(n150_150)
rusage all
.endc
.end
```

| mesh | unknowns | Sparse, before | of which reorder | Sparse, now | of which reorder | KLU |
|---|---:|---:|---:|---:|---:|---:|
| 100 × 100 | 10 002 | 1.5 s | 1.4 s | 0.29 s | 0.17 s | 0.05 s |
| 200 × 200 | 40 002 | 17.8 s | 16.5 s | 3.2 s | 1.9 s | 0.35 s |
| 300 × 300 | 90 002 | 225.8 s | 213 s | 15.6 s | 9.3 s | 1.8 s |

The fill-in is the same as KLU's to within 10 %, so it was not the elimination, and the
equal-valued and random-valued meshes cost the same, so it was not the tie-breaking. The
hunt page blamed the Markowitz scan of `SearchDiagonal`, O(n) per pivot; that scan is real
(2 s of the 226) but it was not the cost. A sampler put 83 % of the run in
`spcColExchange` and `spcRowExchange` and 11 % in `spcCreateElement`, and counters in a
standalone build of the same code, on the 200 × 200 mesh, gave the reason:

| walk | hops (200 × 200) |
|---|---:|
| row and column exchange, through the already-factored parts of the lists | 4.5e8 |
| row and column exchange, through the still-active parts, to reach the two places | 8.5e8 |
| fill-in creation, column walk from the top to the insertion place | 3.1e8 |
| fill-in creation, row walk from the start to the insertion place | 3.1e8 |
| the Markowitz scan itself | 8.0e8 (sequential, cheap) |
| the elimination's own arithmetic | 1.4e8 |

Sparse 1.3 keeps every row and column as a singly linked list sorted by *internal* row
and column number, and an interchange renumbers rows or columns, so moving the chosen pivot
to position `Step` meant, for every element of the two rows (and then of the two columns),
walking its column from the top to find the element's predecessor and then on to the other
position — through the entries of rows and columns eliminated long ago, which the ordering
never reads again, and through the active part it does. Every fill-in walked its column
and its row from the start. On a mesh the fronts grow to hundreds of entries, the walks
grow with them, and the total is quadratic in the node count. Chains and trees have
short lists and never showed it (a 300 000-node ladder orders in 0.3 s), which is why the
character was "known" for large OSDI-heavy decks and never measured.

## What changed

While `spOrderAndFactor` chooses pivots, the lists are kept in an *ordering layout*
(`OrderEnter`, `OrderExit`, `spfactor.c`):

* An entry whose row or column has been eliminated is *finished* and is never relabelled
  or moved by an interchange again. Below the pivot of an eliminated column the entries
  carry `-(external row number)` in `Row`, right of the pivot of an eliminated row
  `-(external column number)` in `Col` — the external number is the identity of the row
  or column, which no interchange changes — and `OrderExit` turns them back into internal
  numbers once the ordering is done (or has failed).
* Finished entries stay where they are in the lists of the active rows and columns until a
  walk meets one; a column walk then moves it to the column's finished list
  (`OrderFinInCol`), a row walk drops it, because `OrderExit` rebuilds the row lists from
  the columns. Every finished entry is met once.
* The active part of a column list is sorted by a key that travels with the row through
  the interchanges (`OrderRowKey`), so the merge in the elimination still works and the
  place of every fill-in is known from the merge; the active part of a row list is not
  sorted, and a fill-in goes to its front (`spcCreateFillin`, O(1)). A row or column
  interchange (`OrderExchange`) relabels the active entries of the two rows or columns
  and swaps the list heads, and nothing else moves.
* `OrderExit` threads all elements into rows sorted by column and then into columns sorted
  by row, two linear passes, and recomputes `Diag`; the lists are then what the sorted-list
  code left, and `spFactor`, `spSolve` and everything after the ordering are untouched.

The Markowitz scan is replaced by a bucket index over the products of the active diagonals
(`OrderIndexBuild`, `OrderPickDiagonal`): one bit set per index in the bucket of its product
(products 0 to 255 have a bucket each, larger ones share a bucket per power of two), with a
summary word per bucket, so the largest index in a bucket, or the largest below a given one,
costs a few words, and an index moves buckets whenever its product is set. The scan had
examined the diagonals with `Step` first and then from the last row upwards, kept the first
acceptable one of each strictly smaller product, accepted at once a product-one diagonal
that dominates a symmetric pair, and checked the relative threshold of what it kept; its
choice is therefore the first, in that order, of the acceptable diagonals with the smallest
product, which the index finds. The one case it cannot decide alone — a smallest product of
zero, where the scan's early acceptance of a product-one diagonal can pre-empt the zero —
goes to the original scan, kept as `QuicklySearchDiagonalScan`. `SearchDiagonal` and
`SearchEntireMatrix`, the fallbacks for a threshold failure, keep their scans;
`SearchEntireMatrix` gathers a column's active part and visits it in ascending row order,
the order the sorted list used to give, because its tie rules depend on it.

The pivot sequence, the fill-in pattern, every arithmetic operation of the elimination and
the final lists are those of the sorted-list code, so the factors, the solves and every
printed number are bit-identical (see Verification); the fast factorization path of
`spOrderAndFactor` (a reorder request on a matrix whose pivots still pass) is the old code
on the sorted lists, and a partial reordering after a threshold failure enters the layout
from that step.

Phase times of one ordering of the 300 × 300 mesh in the standalone driver, before and
after: 226 s → 4.4 s, of which the elimination's own merge and arithmetic 3.2 s, the
interchanges 0.6 s, the rebuild 0.4 s, the pivot search 0.2 s. The remaining growth from
10 000 to 90 000 unknowns (0.09 → 0.9 → 4.4 s) is the fill and the flops of the mesh, as
for KLU's numeric factorization. Inside ngspice an operating point orders twice (`NIiter`
asks for a reorder at the junction-initialised first iteration and again at the
fixed-initialisation second one), which is the 9.3 s of reorder time above; the two
`spFactor` calls that follow (5.5 s) are Sparse's numeric refactorization as before.

## Verification

* **The standalone driver.** `spdrv2.c` builds a matrix straight into Sparse, orders and
  factors it, dumps the pivot maps, every column and row list in list order, every value as
  a hex float, `Diag`, the error and singular indices, the interchange parity, then solves
  and transposed-solves, refactors along the fixed order, and perturbs one diagonal by 1e-9
  so the next `spOrderAndFactor` reorders partially from that step, dumping again. 86
  cases — meshes (1 × 1 to 30 × 30, equal and random values), random resistive networks on
  1 to 60 nodes with values over 4 and 24 decades and negative conductances, MNA networks
  with voltage-source branch rows (with and without `spMNA_Preorder`), complex matrices
  with inductor-like imaginary-only diagonals, chains numbered from either end, singular
  matrices, `pivrel` 0.3, 0.5 and 1 (the `SearchDiagonal` and `SearchEntireMatrix` paths),
  `pivtol` 1e-2 and 1e-1 (rejected diagonals), and a right-hand side (which weights the
  Markowitz counts) — give byte-identical dumps with the old and the new `spfactor.c`.
* **Inside ngspice.** The 122 Sparse decks of the hunt's harnesses (DC, AC, transient,
  noise, pole-zero, sensitivity, distortion, a 300 000-node ladder, the meshes) print the
  same numbers with the E-734 binary and this one; the seven suites that run every check
  under both solvers pass unchanged.
* **The suite.** `solvercore` [N1]: a 150 × 150 mesh (22 502 unknowns) gives the same two
  voltages under both solvers and its "Matrix reorder time" is under 4 s (0.87 s here, 6.2 to 6.4 s
  on the E-734 Sparse, which is the one check the old binary fails); a 30 × 30 RC mesh's
  AC magnitude and phase (the complex ordering); a 10 × 10 mesh with a switch that closes
  mid-transient, shorting two nodes that differ before and agree after.

## What this does not do

* It does not change which pivots Sparse chooses, its fill, its accuracy or its numbers —
  by design. A better ordering for meshes (nested dissection, AMD) is KLU's job; `.option
  klu` is the default.
* It does not touch `spFactor` (the numeric refactorization, 2.7 s per call on the 300 × 300
  mesh) or `spSolve`, nor `spMNA_Preorder`, `spcRowExchange` and `spcColExchange` (still
  used by `spDeleteRowAndCol` when Sparse is built with `DELETE`).
* The `MODIFIED_MARKOWITZ` variant of `QuicklySearchDiagonal`, which ngspice does not
  compile, keeps its array scan.
* Memory: the ordering vectors add about 40 bytes per unknown while a matrix exists
  (3.5 MB at 90 000 unknowns, beside 260 MB of elements).
