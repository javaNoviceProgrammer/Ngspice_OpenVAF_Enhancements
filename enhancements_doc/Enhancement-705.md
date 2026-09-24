# Enhancement-705: a `$table_model` data file of any size compiles — the interval search is a binary tree over the segment's parameters, the MIR post-order walk is iterative and the CFG simplifier no longer restarts at every block it removes; a 100 000-row file overflowed the compiler's stack and 30 000 rows took 189 s, now 3 s

**Scope:** F1 of the
[robustness campaign of 2026-09-23](../docs/bug_hunts/2026-09-23_openvaf-r-robustness-campaign.md),
and the chain-shaped rows of its F7. **Compiler only.** `hir_lower/src/expr.rs`
(`select_tree_multi`, `SELECT_LEAF`; the linear, quadratic, cubic and closest-point
kernels select their segment's parameters through it), `mir/src/flowgraph/transversal.rs`
(`Postorder::dfs` without recursion), `mir_opt/src/simplify_cfg.rs`
(`iteratively_simplify_cfg` takes the next block before it simplifies the current one;
the `const_terminator` expectation in its tests takes the equivalent shape the new order
produces), `hir_lower/src/expr.rs` again (`build_tbl_tree` groups a data file's rows by
sorting them).
`examples/table_model_examples/` (`table_big.va`, `table_iso.va`, five checks, nine per
solver). The handbook row, the compliance document, the hunt page.

**Suites:** [`table_model_examples`](../examples/table_model_examples/) 9 of 9 per solver,
both solvers (on the E-704 binaries the 100 000-row compile aborts and the two checks
behind it do not run: 6 of 9, and the 30 000-isoline compile takes 868 s there); `cubic_table`, `tabledata` 60 of 60, `mdtable`, `ndtable`,
`tablesrc` 57 of 57, `tablearray`, `vaftabledup` 20 of 20, `hunt3diag` 54 of 54,
`lrmkernel` 44 of 44, `vafinstcheck` 41 of 41, `langguard` 132 of 132, `nullarg` 39 of 39
and `lrmfilters` 26 of 26 unchanged, and the E-704 spline probes give the same numbers to
the last digit; the compiler workspace tests green apart from the three pre-existing
sourcegen drift failures (219 passed), no build warnings; full sweep 532 of 532, run alone.

## What was wrong

`I(p,n) <+ $table_model(V(p,n), "iv.dat", "1L");` with a two-column file of `n` rows:

| rows | before | after |
|---|---|---|
| 10 000 | 18.3 s | 1.2 s |
| 30 000 | 189 s | 2.7 s |
| 60 000 | not finished in 420 s | — |
| 100 000 (1.3 MB) | `thread 'main' has overflowed its stack` / `fatal runtime error: stack overflow, aborting`, 4 s in | 9.3 s |
| 1 000 000 | not finished in 300 s | 61.9 s, 6.3 GB |
| 2-D, 10 000 isolines of two points | 15.7 s | 1.45 s |
| 2-D, 30 000 isolines | 133 s | 4.9 s |
| 2-D, 100 000 isolines | the same abort, 8 s in | 18.2 s |

Four things stood on top of each other, and each was measured on its own.

**The search was a chain of branches.** Every compile-time kernel selected its segment
with `result = make_select(x >= grid[i], seg[i], result)` once per knot, and
`make_select` is real control flow — a branch, two arms and a merge with a phi — so a
table of `n` rows lowered to `3n` blocks in one long chain, and every segment's
polynomial was evaluated before the chain chose one.

**The post-order walk recursed.** `Postorder::dfs` (`mir/src/flowgraph/transversal.rs`,
marked "TODO: rewrite this without using recursion") visited the successors of a block
by calling itself, one stack frame per block; the first post-order traversal after the
lowering — the dominator tree the autodiff builds — went 300 000 frames deep on a
100 000-row file and overflowed the 8 MB main-thread stack. `--dry-run` (which stops
before the lowering) exited 0; `--dump-unopt-mir` wrote 182 MB and then aborted.

**The CFG simplifier restarted at every block it removed.** `iteratively_simplify_cfg`
(`mir_opt/src/simplify_cfg.rs`) walked the blocks with a cursor that advanced *after*
`simplify_bb`, through the current block's layout link — "only advance after
simplification to avoid visiting dead blocks". A block that `simplify_bb` had just merged
into its predecessor or dropped as an orphan has that link cleared, so the pass ended
there, `local_changed` sent the loop round again, and the next pass rescanned every block
to find the next one to remove: a 10 000-row table, whose chain leaves about one block
to merge per knot, cost 29 995 passes over 29 997 blocks (17 of its 18 s); 30 000 rows,
189 s. The same quadratic sat under every long chain of `make_select`s — the campaign's
F7 rows for a thousand table calls, five hundred `cross` events and a 200-deep instance
chain.

**The file reader grouped rows by a linear search.** `build_tbl_tree` sorted a file's
rows into isolines by scanning, for every row, the groups seen so far for its
coordinate; on a one-dimensional file every row is its own group, so that was n²/2
comparisons — a third of the 100 000-row file's time once the rest was fixed, and where
a million rows spent their whole 900 s. A stable sort and one pass over the sorted rows
give the same groups in the same order.

With the first two fixed, LLVM took over: the block-placement pass spent ten minutes on
the 300 000 blocks of the chain; with the chain replaced by a tree of branchless
`select`s over the segment *values*, the machine scheduler spent as long on one block
with 100 000 values live at once; and with the tree selecting the segment's *parameters*
instead, the SLP vectoriser spent 25 of 32 s on the 10 000 comparisons it found in one
block (and the C API's switch for it, `LLVMPassBuilderOptionsSetSLPVectorization`, does
not reach the `default<O3>` pipeline). Each was measured with `sample`; none is a defect
of LLVM, they are the costs of a block that is too big.

## What changed

**A binary search over the segment's parameters.** `select_tree_multi` builds the
interval search as a balanced tree: a *branch* on `x >= grid[mid]` while a subtree holds
more than `SELECT_LEAF` (64) knots, a tree of branchless `select`s (E-579's instruction,
which the autodiff differentiates arm by arm) below that, with each comparison emitted
where it is used — at its branch, or inside its leaf's block. Every vector a kernel
hands it is selected through the same structure, so the linear kernel picks its
segment's left knot, value and slope and evaluates *one* line; the quadratic its knot,
value, slope and curvature and one parabola; the cubic its two knots, `1/(6h)`, two
moments and two linear coefficients and one cubic; the closest-point kernel its value.
The per-segment arithmetic is the chain's, in the same order, so every number is bit for
bit what it was — the E-704 spline probes and every table suite say so. What changes is
the shape: about `n / 64` blocks of at most 64 comparisons and 64 selects each instead
of `3n` blocks in a row, so the post-order walk is 17 deep on 100 000 rows, the
simplifier has nothing to merge, and LLVM sees small blocks with short live ranges. And
an evaluation costs `log2 n` branches plus one leaf — a 100 000-row table now runs 11
branches, 64 comparisons and one line where it used to evaluate 100 000 lines and walk
100 000 merges. Tables of up to 64 knots — nearly every table in a real model — lower
to selects alone, no branch at all.

**The post-order walk is iterative.** `Postorder::dfs` keeps an explicit stack of
(block, next successor) frames with exactly the recursive order — a block joins the
result after all its successors, successors in edge order, a block reached again is not
re-entered — so no control-flow shape can overflow the compiler's stack there.

**The simplifier's cursor.** `iteratively_simplify_cfg` reads the next block *before*
it simplifies the current one. `simplify_bb(bb)` removes no block but `bb` itself, so
the next block is still in the layout when it is visited, and a block that became an
orphan meanwhile is dropped on its own visit as before; a pass now removes everything it
can, and the loop converges in a few passes instead of one per block. Its unit test
`const_terminator` sees the same function threaded through the other arm — the branch
that is folded first changed with the order — and its expectation was updated to that
equivalent shape (the phi carries the same two constants from the two paths).

**The file reader sorts.** `build_tbl_tree` groups a file's rows by a stable sort on
the axis coordinate and one pass over the result: ascending groups, rows in file order
within a group, the first of duplicate rows at the leaf, exactly as before.

## Verification

`table_model_examples` (nine checks per solver): the 100 000-row file compiles (13.5 s,
it aborted the compiler), five points inside it — the first segment, 0.12345, 3.14159,
7.77777 and the last segment — are the exact linear interpolation (5.9e-17 A), the AC
conductance at 3.14159 is the segment's slope (5.6e-17 S) — the derivative through the
tree — and the 30 000-isoline two-input file compiles (9.4 s, 133 s before) and gives
12 345.75 at (12 345.5, 0.25), the bilinear value. By hand: the table above; the E-704
spline probes (file and run-time forms, `3C`/`3CC`/`3LC`/`3CL`/`3L`, the `ddx` across
the edges) unchanged to the last digit; and the campaign's other chain-shaped probes:
a thousand calls of one ten-point table 65 s → 29 s (each call's chain is now a leaf
tree), 5 000 nested `if`s 4.4 → 3.7 s and a 5 000-item `case` 4.9 → 4.4 s (the
simplifier's cursor), while five hundred `cross` events (120 → 114 s) and the 200-deep
instance chain (208 → 208 s) are not chains of selects and are not changed.

## What this does not do

- The compile-time **cubic** spline still inverts a dense n × n moment matrix (F2 of the
  campaign): 2 000 knots 69.9 s (77 s before), 4 000 not in 300 s. The chain is gone from it; the
  matrix is not.
- The **run-time array form** keeps its chains and E-392's 256-knot cap; its arrays are
  small by construction.
- F7's other rows — a `localparam` array literal, a loop over an array, an inline
  `noise_table`, a `laplace_nd` coefficient list — are not chains of branches and are not
  changed by this: the 20 000-value `localparam` array 15.0 s (15.5 s before), the
  10 000-element fill loop 24.6 s (27 s), a 5 000-pair inline `noise_table` 59.4 s (58 s).
- `SELECT_LEAF` is 64 by measurement on this machine (a leaf of 64 comparisons and
  selects is well inside what LLVM handles linearly); it is a constant, not an option.
