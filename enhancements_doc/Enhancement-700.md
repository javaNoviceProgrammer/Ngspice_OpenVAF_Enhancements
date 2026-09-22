# Enhancement-700: four diagnostic slips around the filters and tables — a short data file was "unreadable", a null denominator drew two errors, a Laplace `abstol` of zero passed, and the run-time table form refused `E` as "unsupported" under a note that listed it

**Scope:** F7 of the
[bug hunt of 2026-09-21 on the filters, tables and noise sources](../docs/bug_hunts/2026-09-21_openvaf-r-filters-tables-and-noise.md).
openvaf: `hir_ty/src/validation.rs` (`table_file_problem`, the reason behind
the old `table_file_is_usable` bool, and the `TableFileUnusable` report built
with it in `to_report`), `hir_ty/src/inference.rs` (`infere_laplace`: no type
mismatch beside the coefficient check), `hir_ty/src/validation/body.rs` (the
empty-coefficient message, the Laplace `abstol` check, `table_ctrl_problem`
without the run-time-form refusals), `hir_lower/src/expr.rs`
(`apply_end_extrap_at`, the run-time branch of `lower_table_model`).
`examples/lrmfilters_examples/` (a sixth section, four checks, 26 per solver),
`examples/nullarg_examples/` (four checks, 39), `examples/tablesrc_examples/`
(`refused/short_columns.va` with `two_col.dat`, 67),
`examples/langguard_examples/` (five pins inverted, eight value checks added,
119). The compliance document and the handbook rows, the two suite READMEs,
the hunt page.

**Suites:** [`lrmfilters_examples`](../examples/lrmfilters_examples/) 26 of 26
per solver, both solvers (24 of 26 on the E-699 binaries);
[`nullarg_examples`](../examples/nullarg_examples/) 39 of 39 (35 of 39);
[`tablesrc_examples`](../examples/tablesrc_examples/) 67 of 67 (66 of 67);
[`langguard_examples`](../examples/langguard_examples/) 119 of 119 (106 of the
111 it can run there: the five controls it now accepts are refused, and the
eight value checks behind them do not run); `tablearray`, `vaftabledup`,
`vafopenitems`, `vafinstcheck`, `natureref`, `natureexpr`, `argcheck`,
`limguard`, `arraycast`, `complexpole`, `filterforms`, `tablefix`,
`cubic_table`, `mdtable`, `ndtable`, `lrmnoise`, `noisetable`, `vaflaplace`,
`constguard`, `deckdomain`, `dropguard`, `lrmops` and `lrmfuncs` both solvers,
unchanged; the compiler workspace tests green apart from the three
pre-existing sourcegen drift failures; full sweep 531 of 531, run alone.

## What was wrong

Four messages that did not say what was wrong, found in one hour of probing
the filters, `$table_model` and the noise sources against the LRM:

- `$table_model(0.5, V(in), "two_col.dat")` — two inputs on a readable
  two-column file — was refused as "cannot use 'two_col.dat' as $table_model
  data: missing, unreadable, or contains no usable table data", under notes
  about non-finite values and the path. The file was fine; it lacked a column
  (LRM 9.21.1: N inputs need N + 1 columns). `table_file_is_usable` answered
  a `bool`, so every cause — a missing file, a `nan`, a ragged row, the column
  shortage, a grid header that does not add up — got the one label.
- `laplace_nd(V(in), '{1}, )` — a null argument where 4.5.11 allows one for
  the zeros vector only — drew two errors: "type mismatch: expected real value
  but found _[0:0] value" (the empty array's internal spelling, pushed by
  `infere_laplace`) and then the one that matters, "the denominator is an
  empty coefficient list; it needs at least a constant term". Neither named
  the null argument or the rule.
- `laplace_nd(V(in), '{1}, '{1, 1e-3}, -1e-9)` and a `0.0` there compiled in
  silence, where `ddt(V(in), -1e-9)` is refused with "the absolute tolerance
  must be greater than zero". The handbook claimed the Laplace tolerance was
  validated like `ddt`'s; the validator's Laplace arm checked the orders and
  the constant-ness and never the sign.
- `$table_model(V(b), xs, ys, "1E")` on the run-time array form was refused as
  "unsupported $table_model control string "1E"", and the report's own note
  listed "'E' (error)" among the supported codes; `"1CL"` and `"1LC"` were
  refused the same way. The restriction was the form's — its kernels keep a
  single linear/clamp switch — not the string's.

## What changed

- **The file check returns its reason.** `table_file_problem` replaces the
  bool (which is now `table_file_problem(..).is_none()`, so the noise-table
  and duplicate-knot callers are untouched) and names the cause: "the file is
  missing or cannot be read", "line 3 holds 'nine', which is not a number",
  "line 4 holds 'inf', which is not a finite number …", "the file holds no
  numeric rows", "line 7 has 2 columns where the first row has 3 …", "its rows
  have 2 columns, but the call has 2 inputs and needs at least 3 (LRM 9.21.1:
  the 2 independent columns first, then the dependent ones)", "a noise table
  is two columns, frequency and power, and its rows have 3", or, for a
  well-formed self-describing grid header whose count does not add up, what it
  accounts for against what the file holds. `to_report` builds the
  `TableFileUnusable` report with that reason as its label and keeps the two
  notes that apply to every cause (the path rule, the old silent zero).
- **One error for a null denominator.** `infere_laplace` no longer pushes the
  type mismatch for an empty direct denominator; it marks the call invalid and
  leaves the message to the validator's coefficient check, which now reads "is
  an empty coefficient list (a null argument, or '{}'); it needs at least a
  constant term — LRM 4.5.11 allows a null argument for the zeros vector only".
  The `zi_*` spelling (`zi_nd(V(in), '{1}, , 1u)`) reads the same, once.
- **The Laplace `abstol` is a magnitude.** The validator's Laplace arm runs
  `require_positive` on the optional trailing argument, exactly as the
  `ddt`/`idt`/`idtmod` arm does: "laplace_nd: the absolute tolerance must be
  greater than zero, but is -0.000000001". A nature does not fold to a number
  and passes through, as there; a positive real passes.
- **The run-time array form takes `E` and per-end methods.** `lower_table_model`'s
  run-time branch sets the kernels' switch to linear when either end asks for
  it and then applies the per-end methods to the result against the sorted
  grid's run-time endpoints (`apply_end_extrap_at`, the core of
  `apply_end_extrap` with `Value` endpoints, which the compile-time path now
  calls too): a clamped end beside a linear one, and `E` with the same fatal
  the compile-time grid raises. `table_ctrl_problem` drops the two refusals;
  `D` and `I` stay refused there, with messages that say so. On `y = x²`
  sampled at 0, 1, 2: `"1LC"` gives −1 below and 4 above, `"1CL"` 0 and 7,
  `"3CL"` 0 and the spline tangent's 7.5, `"1E"` 2.5 inside and the
  "above the table" fatal at 3.

## Verification

| check | new | E-699 binaries |
|---|---|---|
| two inputs on a two-column file | "its rows have 2 columns, but the call has 2 inputs and needs at least 3 …" | "missing, unreadable, or contains no usable table data" |
| `laplace_nd(V(in), '{1.0}, )`, `laplace_zd(V(in), '{-1e4,0}, )` | one error each, naming the null argument and the zeros-only rule | two errors each, the first spelt `_[0:0]` |
| `laplace_nd(…, -1e-9)`, `laplace_nd(…, 0.0)` | refused: "the absolute tolerance must be greater than zero" | compile |
| `laplace_nd(…, 1e-9)`, `laplace_nd(…, Voltage)` | compile | compile |
| run-time `"E"`, `"1E"`, `"1CL"`, `"1LC"`, `"3CL"` | compile | "unsupported $table_model control string" |
| run-time `"1LC"` at −1 / 3, `"1CL"` at −1 / 3, `"3CL"` at −1 / 3, `"1E"` at 1.5 | −1 / 4, 0 / 7, 0 / 7.5, 2.5 | — |
| run-time `"1E"` at 3 | the `$table_model` "above the table" fatal | — |
| `D`, `I`, `Q` on the run-time form | still refused, by name | refused |

## What this does not do

The `E` the run-time form now honours is the same check the compile-time grid
runs, judged on every Newton iterate — F2 of the same hunt, still open — so a
run-time table whose domain excludes the zero initial guess aborts under `E`
as a file table does. `D` and `I` remain compile-time-grid features on the
run-time form. A null numerator (`laplace_nd(x, , den)`, H = 0) is accepted as
before (E-453 pins it), and the noise-table file check keeps its own report.
