# Enhancement-562: `$table_model` reads its data from arrays of any dimension, ignores columns with `I`, interpolates with the quadratic spline `2`, and takes a `localparam string` as file name or control string

**Scope:** the lookup-table gaps (§3.5) of the
[coverage audit of *A Practical Guide to Verilog-A*](../docs/audits/2026-09-05_practical-guide-verilog-a-coverage.md).
Type inference and its diagnostics (`openvaf/hir_ty/src/{inference,diagnostics,builtin}.rs`),
validation (`openvaf/hir_ty/src/validation.rs`, `validation/body.rs`), a new
`openvaf/hir_ty/src/table_source.rs` shared by validation and lowering, two scope
accessors (`openvaf/hir_def/src/{lib,nameres}.rs`), the HIR (`openvaf/hir/src/{lib,body}.rs`)
and the lowering (`openvaf/hir_lower/src/expr.rs`). **Compiler only; ngspice is unchanged.**

**Suites:** new [`tablesrc_examples`](../examples/tablesrc_examples/) (66 checks per
solver, both solvers); `table_model`, `cubic_table`, `mdtable`, `ndtable`, `tablefix`,
`vaftabledup`, `tabledata`, `noisetable`, `array`, `laplace`, `concat` pass; three
suites that pinned the old refusals were re-pinned to the new behaviour (`langguard`'s
control-code list, `lrmkernel`'s quadratic check now exact on linear data, and the
LRM's own page-274 array-source example promoted from `lrm_examples/limitations/` to
`va/`); full sweep 460 of 460 with them; the compiler's front-end crate tests pass;
the 92-model corpus compiles as before (91 of 92 standalone, the EPFL-HEMT baseline).
Handbook
[§2.11](../docs/handbook/02-verilog-a-language.md), the
[compliance matrix](../docs/compliance/OpenVAF_Verilog-A_LRM_Compliance.md) §7 and §9,
the suite README.

## What was wrong

LRM 9.21 gives `$table_model` two data sources — a file, or *arrays* — and the book
teaches the array form the way the clause writes it: fill `y[i]`, `x[i]`, `f[i]` in
an `analog initial` block, then `$table_model(yy, xx, y, x, f)`; or hold the table in
one 2-D array whose rows are the columns. Only Enhancement-389's 1-D runtime pair
`(x, xs, ys)` existed; every other array shape was refused with *'y' requires a
bit-select [i]* (the audit's `u22`, `u23`). The grammar also allows a
`string_parameter` as the file name, and the book passes the control string as a
parameter; both were *type mismatch* (`u21`). Of Table 9-30's codes, `2` (quadratic
spline) and `I` (ignore this column) were still *unsupported control string*
(`u25`, `u27`, `t26c`).

## What changed

* **The array data source, any dimension.** After the k coordinate inputs, one 1-D
  array per column — the independent columns, an `I`-ignored column included, then
  the dependent column(s) — or a single 2-D array whose rows are those columns, then
  the optional control string. The columns become the rows of the same N+M table a
  data file holds and go through the same isoline tree, so the two sources cannot
  disagree; the `;N` selector, per-axis controls and ragged isolines all apply. A
  wrong shape (fewer than k+1 arrays, a 2-D array among several) is *invalid array
  data source for $table_model* with the rule spelled out. The 1-D runtime shape
  keeps Enhancement-389's runtime kernels; a `localparam` array now takes that path
  too (it used to fall through to an empty table).
* **The arrays are compile-time constants, and the compiler says why not.** The
  table is built when the model is compiled, so each element must be its declaration
  initialiser, or a single straight-line assignment — in `analog initial`,
  `@(initial_step)` or the analog block itself, not under a condition, in a loop or
  through a function argument — of a literal or a `localparam`. One evaluator
  (`table_source.rs`) decides for both validation and lowering; a violation is
  *$table_model array data 'y' is not a compile-time constant* with the element and
  the reason (*written at run time …*, *is an overridable `parameter` … declare the
  array `localparam`*), and the note points at the 1-D runtime form for data computed
  at run time.
* **`I`** drops the named column of a data file or of the array form before the
  remaining leading columns are taken as the inputs (`"I,1L,1L"` on a
  `tag y x f` file). On the runtime 1-D form and on inline `'{...}` data — which
  have no column to drop — it stays a located refusal.
* **`2`** is the C1 quadratic spline: knot slopes `z_0 = s_0`, `z_{i+1} = 2 s_i − z_i`
  from the chord slopes; interval i is `v_i + z_i·dx + (z_{i+1} − z_i)/(2h_i)·dx²`;
  `L` continues the end tangents, `C` and `E` behave as for the cubic. A runtime
  twin serves the 1-D array form, passing the slope through the compacted duplicate
  knots so the upper tangent belongs to the last live knot.
* **A `localparam string`** is accepted wherever the grammar says
  `string_parameter` — file name or control string, through any chain of
  `localparam`s. An overridable `parameter string` is refused: *the $table_model
  control string must be a compile-time constant string — an overridable `parameter
  string`, which the model card may replace after the table has been built*.
* Whole-array arguments of **multi-dimensional array variables** now resolve their
  elements (the 1-D spelling produced names no element has), and every array
  argument records its shape for the consumers that need it.

## Verification

| check | result |
|---|---|
| `$table_model(yy, xx, y, x, f)`, columns filled in `analog initial`, f = 2x + y on ragged isolines | exact at (1.5, 0.25), (4, 0.75), (2.5, 0.5), extrapolated (6, 1.5), (0.5, −0.5) |
| `$table_model(yy, xx, tab)` with `real tab[0:2][0:10]` (rows y, x, f) | the same five values |
| `localparam` arrays + `localparam string` control and file name | 2·(2x + y) |
| `"I,1L,1L"` on a four-column file; `"I,1,1"` on four arrays | 2·(2x + y) |
| `"2L"`/`"2C"` on x² knots 0..3, inline and runtime, at 0.5, 1.5, 2.25, −1, 4 | equal to the Python spline (−1 → −1 / 0, 4 → 14 / 9) |
| overridable `parameter string`; `parameter` array; array written under `if`; `I` on runtime arrays; `I` on inline data; two arrays for two inputs | each refused with its named diagnostic |
| the audit's `u22`, `u23`, `u25`, `u27`, `t26c`; the LRM's page-274 example | compile; `u21` refused as a `parameter string` control |
| `tablesrc_examples`; eleven table/array suites; the three re-pinned suites; full sweep | 66 / 66 both solvers; all pass; pass; 460 of 460 |
| front-end crate tests; model corpus | pass; 91 of 92 standalone (baseline) |
