# Enhancement-702: the run-time array `$table_model` captures its data at the first evaluation — a knot computed from the solution made a different table at every iterate, in silence

**Scope:** F6 of the
[bug hunt of 2026-09-21 on the filters, tables and noise sources](../docs/bug_hunts/2026-09-21_openvaf-r-filters-tables-and-noise.md).
openvaf: `hir_ty/src/table_capture.rs` (`captured_table_data`, the analysis),
`hir_ty/src/inference.rs` (`InferenceResult::captured_table_data`, filled at
the end of inference), `hir/src/body.rs` (`BodyRef::table_data_captured`),
`hir_lower/src/expr.rs` (`capture_table_data`, called from the run-time branch
of `lower_table_model` after the sort for the tables that analysis names),
`hir_lower/src/state.rs` (the flag reset in `insert_var_init`),
`hir_lower/src/lib.rs` (`HirInterner::table_capture_flags`),
`hir_lower/src/stmt.rs` (`new_event_state` opened to the crate),
`hir_ty/src/validation/body.rs` (`lint_table_data_captured`, which reports the
analysis's entries; the `TableDataCaptured` diagnostic),
`hir_ty/src/validation.rs` (its lint mapping and report), `basedb/src/lints.rs`
(`table_data_captured`, L038). `examples/tablesrc_examples/`
(`tablesrc_capture.va`, `tablesrc_recapture.va`, a seventh section of eight
checks, 57 per solver; the README's count corrected). The compliance document
and the handbook row, the suite README, the hunt page.

**Suites:** [`tablesrc_examples`](../examples/tablesrc_examples/) 57 of 57 per
solver, both solvers (54 of 57 on the E-701 binaries: the warning and the two
captured values); [`vafinstcheck_examples`](../examples/vafinstcheck_examples/)
41 of 41 (its 256- and 200-knot run-time cubic tables);
[`langguard_examples`](../examples/langguard_examples/) 119 of
119, [`lrmfilters_examples`](../examples/lrmfilters_examples/) 26 of 26,
[`nullarg_examples`](../examples/nullarg_examples/) 39 of 39, both solvers,
unchanged; every example model that calls `$table_model` (43 of them) compiled
against the new compiler — one draws the new warning,
`tablesrc_examples/refused/runtime_ignore.va`, a refused case; the compiler
workspace tests green apart from the three pre-existing sourcegen drift
failures (219 passed), no build warnings; full sweep 532 of 532, run alone.

## What was wrong

LRM 9.21.1: "The state of the data source is captured on the first call to the
table model function. Any change after this point is ignored." The 1-D array
form whose data the body computes — [E-389](Enhancement-389.md)'s "two array
variables filled in by the body" — lowered the knots as ordinary MIR values, so
a knot written from the solution was re-read at every evaluation:

```verilog
xs[0] = 0.0; xs[1] = 1.0; xs[2] = 2.0;
ys[0] = 0.0; ys[1] = 1.0 + V(a,b); ys[2] = 4.0;
I(a, b) <+ $table_model(V(a,b), xs, ys);
```

compiled without a word and gave 0.75, 2.0 and 3.25 over `dc vb 0.5 1.5 0.5`:
a different table at each sweep point, and within a point a different table at
each Newton iterate. The same data in an `@(initial_step)` block gave the
clause's answer, 0.5, 1.0 and 2.5 — the table `{0, 1, 4}` read once. The
analogous case for a `laplace_*` coefficient at least draws a compile-time
warning that the vector will TRACK; this one drew nothing.

## What changed

**The capture.** After the run-time branch of `lower_table_model` has trimmed
and sorted the knots of a table whose data depends on the solution (which
tables, below), `capture_table_data` latches each of them into a
persistent per-call-site slot — the `EventState` slots of
[E-8](Enhancement-8.md), which the OSDI instance reads at the start of every
evaluation and stores at its end — and hands the kernels the latched values.
The latch is a `select` on a capture condition: the instance's first evaluation
(`IsInitialStep`), or a per-call-site "captured" flag still at zero. The flag
is set to one at the call site once the data is stored, and cleared at every
initial step in the function's entry block (`insert_var_init`, the pass that
already applies the variable initializers there) — so a call site the first
evaluation does not reach, a table inside a region `if` whose condition the
initial guess fails, captures at its own first evaluation of the analysis
instead of reading zeroed slots, and a re-setup captures afresh.

**Which tables.** One analysis, run at the end of inference
(`table_capture::captured_table_data`) and stored in the inference result,
decides both what the lint reports and what the lowering latches, so the two
agree by construction. A table built from parameters, constants, the
temperature or an `@(initial_step)` fill is left live: its data cannot change
between two setups, and ngspice sets the instance up again wherever it could
(below), so nothing about that table changes — and it keeps the compile-time
folding of its interpolant. A first cut latched every run-time table; it turned
`vafinstcheck`'s 256-knot literal cubic table, which folds to a select chain
today, into an evaluation-time spline, and the compiler overflowed its stack on
it — as it does, on the E-701 binaries too, for an `@(initial_step)`-filled
table of that size: a pre-existing limit of the evaluation-time cubic kernel,
reached between 100 and 200 knots.

**What "first evaluation" means in ngspice.** `OSDIsetup` and `OSDItemp` clear
the instance's `has_evaluated`, and `CKTtemp` runs at every analysis start, at
every point of a `dc` sweep of a device, model or temperature parameter
([E-534](Enhancement-534.md)'s one `CKTtemp` per point) and after `alter`. The
live tables follow every one of those, exactly as before, and a latched one —
data from the solution or the time — is read at the first evaluation of each
analysis, the initial guess for an `op`, `t = 0` for a transient, and held. The
sort runs on the live values ahead of the latch; a latched table pays two
loads, two `select`s and two stores per knot per evaluation.

**The warning.** A new lint, `table_data_captured` (L038, warn by default,
`-E table_data_captured` raises it), reports the data array of a run-time 1-D
table when its value depends on a potential, a flow, `$abstime` or
`$realtime`. The dependence is traced as [E-686](Enhancement-686.md) traces
`$mfactor`: by variable name over the whole body, through assignments, through
the element index of an array write, and through the controls of `if`, `case`,
loop and event statements (an element assigned under `if (V(a,b) > 1)` depends
on the solution through the path taken); an assignment inside
`@(initial_step)` does not taint, since it runs at the first evaluation only,
which is the capture. The report quotes the clause, says where the capture
happens, and points at the two ways to keep the dependence — on the input or
on the result — and at `(* openvaf_allow="table_data_captured" *)`. Data from
parameters, constants or the temperature draws nothing.

## Verification

`tablesrc_examples` section 7: `tablesrc_capture.va` (a knot `1 + V(a,b)`)
builds with L038 and gives 0.5, 1.0, 2.5 over the sweep and 1.0 at 1 V
(tracking gave 0.75, 2.0, 3.25 and 2.0); with its call site gated by
`V(a,b) > 0.7`, an `op` at 1.5 V captures at the second evaluation, the first
that reaches the site (3.25 mA, the table `{0, 2.5, 4}`; zeroed slots would
give 0), and an `op` after `alter vin = 1.2` captures afresh (2.56 mA; a
capture that never repeated would give 2.8). `tablesrc_recapture.va` (knots
from an instance parameter `p` and `$temperature`, the call site gated the same
way) builds without L038 and, left live, follows a `dc` sweep of `p` (2.50025,
5.0005, 7.50075 mA), a `dc temp` sweep (2.50025, 2.58358, 2.66692 mA at 27, 77
and 127 °C) and an `op` / `alter p=2` / `op` pair (2.50025, 5.0005 mA). On the
E-701 binaries the warning and the two captured values fail and the rest pass,
which is the change in one line. `vafinstcheck` 41 of 41: its 256-knot and
200-knot run-time cubic tables of literal data fold as before (the first cut
failed both — the compiler overflowed its stack on the evaluation-time
spline). Probed by hand beyond the suite: a knot `1 + $abstime·1e6` under
`tran` holds 2.5 mA from `t = 0` on; the taint reaches an element through a
scalar (`t = V(a,b); ys[1] = 1 + t`), through a flow probe and through an `if`
on the solution; the allow attribute silences it; two call sites in one module
keep separate slots (an `alter` of one's parameter moves only that table); a
`for` loop filling both arrays with dynamic indices captures the right values.
Every example model that calls `$table_model` was compiled: none but a refused
case draws the warning, so no suite relied on the tracking. The README's "67
checks" was a stale count; the suite has 49 checks before this section and 56
with it.

## What this does not do

- The capture is per evaluation, not per converged solution: a table whose data
  depends on the solution is built from the initial guess (or from the previous
  sweep point's solution where ngspice sets the instance up again per point).
  That is the clause's "first call", and the warning is there because it is
  rarely what the author meant.
- `laplace_*` coefficients keep the TRACK policy the compliance document
  records; only `$table_model` gets the freeze, because 9.21.1 states it for
  the data source in so many words, and a filter's coefficients are also its
  state.
- The compile-time array forms (a literal, a file, E-562's constant arrays) are
  untouched: their data is read when the model is compiled.
- A table call inside a loop body is one call site with one set of slots: the
  data of the loop's last pass is what it captures (no example does this).
- An evaluation-time cubic table of 200 knots or more — data that depends on
  the solution, or an `@(initial_step)` fill, on the E-701 binaries as here —
  overflows the compiler's stack; 100 knots compile. Constant data folds at
  compile time at any size up to the sort cap of 256, as before.
