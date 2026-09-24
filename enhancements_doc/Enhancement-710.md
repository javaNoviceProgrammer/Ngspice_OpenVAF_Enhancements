# Enhancement-710: the cubic spline's moments are solved by the Thomas algorithm, and a file with a table above 4 096 knots is optimised without LLVM's SLP vectoriser — a 2 000-knot `"3L"` data file took 77 s and 1.4 GB through a dense n × n operator, 4 000 knots did not finish in 300 s, 200 000 filled 50 GB; 10 000 knots compile in 1.5 s now and 200 000 in 41 s

**Scope:** F2 of the
[robustness campaign of 2026-09-23](../docs/bug_hunts/2026-09-23_openvaf-r-robustness-campaign.md).
**Compiler only.** `hir_lower/src/expr.rs` (`SplineMomentSystem`,
`cubic_spline_moment_system`, `cubic_spline_moments`, `linear_combination`;
`LARGEST_SELECT_TREE`, recorded by `select_tree_multi`), `hir_lower/src/lib.rs`
(re-export), `mir_llvm/src/lib.rs` (`disable_slp_vectorizer`), `osdi/src/lib.rs`
(`SLP_TABLE_KNOTS_LIMIT`, the decision in `compile`).
[`examples/cubic_table_examples/`](../examples/cubic_table_examples/) (`cubic_big.va`,
7 checks, 18 in all). The suite README's "How it stays differentiable", the handbook's
`$table_model` row, the compliance document's 9.21 entry, the hunt page.

**Suites:** `cubic_table` 18 of 18 per solver, both solvers (on the E-709 binaries the 10 000-row compile times out at 120 s and the six
checks behind it do not run), `langguard` 132 of 132 (E-704's clamped-end rows to the last digit),
`table_model`, `tablesrc`, `tabledata` 60 of 60, `mdtable`, `ndtable`, `lrmkernel`,
`vafinstcheck` 41 of 41, `hunt3diag`, `tablearray`, `vaftabledup` 20 of 20,
`lrmfilters` and `vafcrash2` 22 of 22 unchanged; the compiler workspace tests green
apart from the three pre-existing sourcegen drift failures (221 passed), no build
warnings; full sweep 532 of 532, run alone.

## What was wrong

A `"3L"` table from a data file of n rows:

| knots | before | now |
|---|---|---|
| 1 000 | 6.8 s | 0.6 s |
| 2 000 | 77 s, 1.4 GB | 0.6 s |
| 4 000 | not finished in 300 s | 1.4 s |
| 10 000 | not finished in 300 s | 1.5 s |
| 30 000 | not finished in 300 s | 5.1 s |
| 100 000 | not finished in 300 s | 19.1 s, 1.9 GB |
| 200 000 | not finished in 300 s, **50 GB** resident | 41.2 s, 3.8 GB |

Two causes, one behind the other.

**The dense operator.** Enhancement-22 expressed the spline's moments (the second
derivatives at the knots) as a linear operator on the data values — the n × n matrix
T⁻¹·R, with the tridiagonal T inverted by Gauss–Jordan — so that a table whose values
are run-time expressions still lowered without a run-time solve; each moment was then
a weighted sum over all n values. The inverse of a tridiagonal matrix is dense, so
building the operator was O(n³) time and O(n²) memory, and applying it O(n²) MIR
instructions. Doubling the knots multiplied the time by eleven. For a data file, an
inline literal or a `localparam` array the values are constants and the operator was
applied to constants. Enhancement-704 added the clamped-end rows to the same matrix
and inherited its cost; Enhancement-705, which made the interval search a tree, noted
the matrix as the cubic kernel's remaining chain.

**The SLP vectoriser.** With the moments solved in O(n) the 10 000-knot table
compiled in 1.5 s, 30 000 in 32 s and 100 000 not in 400 s: `sample` put 27 of the
32 s in LLVM's SLP vectoriser — `optimizeGatherSequence`, a common-subexpression pass
over every gather instruction the vectoriser created in the function, quadratic in
their number. The cubic kernel selects seven parameters per knot through the
Enhancement-705 tree, and the seven parallel select trees of a leaf are the
vectoriser's ideal input; the linear kernel's three lanes pay the same tax at a
smaller rate (100 000 rows: 9.3 s in Enhancement-705, 8.1 s now). A narrower leaf did
not help (16 knots: the same 32 s), and `LLVMPassBuilderOptionsSetSLPVectorization`
has no effect on the `default<O3>` pipeline in this LLVM 18 build, as Enhancement-705
had already found.

## What changed

1. **The Thomas algorithm.** `cubic_spline_moment_system` factors the tridiagonal
   system once, in O(n): the sub-diagonal, the pivots of the forward elimination and
   the eliminated super-diagonal, and each row's right-hand side as at most three
   (weight, value) terms. The end conditions are Enhancement-704's, unchanged: a
   natural end's moment is zero outside the system, a clamped end's joins it with the
   zero-derivative row. `cubic_spline_moments` then solves for the data: when every
   value is a constant — a data file, an inline literal, a `localparam` array — the
   forward sweep and back substitution run in f64 and each moment is one constant;
   when the values are run-time expressions (an N-D slice of a larger table) the same
   sweep and substitution are emitted as straight-line MIR, linear in the data and so
   differentiable, about ten instructions per knot. A degenerate system (a zero pivot,
   which the validated strictly increasing grid cannot produce) gives zero moments, as
   the singular inverse did. The dense operator and `weighted_sum` are gone.
2. **No SLP vectoriser above 4 096 knots.** `select_tree_multi` records the widest
   tree it lowers in `LARGEST_SELECT_TREE`; before it spawns the code-generation
   threads, `osdi::compile` calls `mir_llvm::disable_slp_vectorizer` when that width
   is above `SLP_TABLE_KNOTS_LIMIT` (4 096 — a 4 000-knot cubic table compiles in
   1.4 s with the vectoriser on). The switch is LLVM's own command-line option,
   `-vectorize-slp=false`, parsed once through `LLVMParseCommandLineOptions`, which
   does take effect where the pass-builder option does not; it is process-wide, which
   is why the decision is made before the first pass pipeline is built. Every other
   file — the largest compact models included: HiSIM2's evaluation function is
   155 000 MIR instructions and compiles in its usual 1.5 s — is compiled exactly as
   it was.

## Verification

`cubic_table_examples` gains section [6]: a 10 000-row `"3L"` file (x = i/1000,
y = sin x) compiles within 120 s — 1.5 s here, where the E-709 binaries do not finish
— and at three interior points its value equals the natural spline computed in
Python by the Thomas algorithm on the same data to 1 part in 10⁹, and its AC gm equals
that spline's derivative to 1 part in 10⁶. The eleven existing checks — accuracy
against sin, the continuous gm, the straight line reproduced to 10⁻⁹, the 2-D
tensor-product spline (the run-time route: each inner slice's moments are the
straight-line MIR of the new solver) and Enhancement-704's exact fractions (125/56,
131/56, 1799/776, 1751/776, 16 + 720/97, −48/97, 5577/1400 at 1 part in 10⁷) — are
unchanged, as is `langguard`'s clamped-end row. By hand: the table above; the
30 000-knot profile before and after the switch (32 s to 5.1 s); HiSIM2 and BSIM4
compile in the same time as before (1.5 s and 3.2 s).

## What this does not do

- The moments are numerically the Thomas algorithm's, not the dense operator's:
  the two agree to rounding (the suites' 10⁻⁷ and 10⁻⁹ tolerances hold), but a value
  is no longer bit for bit what Enhancement-22 produced, unlike Enhancement-705's
  rewrite of the interval search.
- The SLP switch is process-wide and keyed on the widest table in the file, not on
  the function that holds it: a file that mixes a 10 000-knot table with a compact
  model compiles the model without the vectoriser too. The limit is a constant, not
  an option.
- The run-time array form (E-390's Thomas solve in MIR over run-time knots) keeps its
  256-knot cap.
