# Enhancement-588: a port probe on a bus element, lint L029 for reserved parameter names, and three diagnostic slips

**Scope:** `openvaf/parser/src/grammar/{expressions,stmts}.rs`, `parser/src/error.rs`,
`syntax/src/{error.rs,parsing/tree_builder.rs,ast/node_ext.rs}`,
`basedb/src/{lints.rs,diagnostics/syntax_error.rs}`, `hir_def/src/{body/lower.rs,
item_tree/lower.rs,nameres/collect.rs,nameres/diagnostics.rs}`, `hir/src/lib.rs`,
`hir_ty/src/validation/body.rs`, `sim_back/src/module_info/tests.rs` (a snapshot gains
the lint's lines), `examples/hunt2diag_examples/` (new, 15 checks per solver).
**Compiler only.** Hunt findings F5, F6, F7a, F7f and F7h of 2026-09-07; F8 is
withdrawn (see the end).

**Suites:** [`hunt2diag_examples`](../examples/hunt2diag_examples/) 15 of 15 per
solver, both solvers; `cargo test` for parser, syntax, hir_def, hir_ty, hir_lower and
sim_back (one snapshot gained the new lint's lines); full sweep 483 of 483.

## What changed

* **F5 — `I(<a[1]>)`.** A port-branch probe on a bus element was *unexpected token '['
  expected '>'* while `I(a[1], c)` and `$port_connected(a[1])` took the bit-select. The
  parser accepts `<name[±int]>` and keeps the tokens in the PORT_FLOW node;
  `ast::PortFlow::bus_index` reads them back; the expression lowering and the branch
  declaration lowering map the pair to the synthesized `a[1]` node exactly as
  `resolve_branch_endpoint` does for `(a[1], c)`. An out-of-range element is refused as
  before.
* **F6 — lint L029 `reserved_parameter_name`** (warn, case-insensitive). A module
  parameter named `m`, `temp`, `dtemp` or `dt` receives the netlist's `m=`/`temp=` and
  ngspice's own meaning is lost without a word: `m=4` no longer multiplies (`$mfactor`
  stays 1) and `temp=100` never reaches `$temperature`. L018 warned about a *module*
  name colliding with a SPICE model type; this is the same gap at the parameter level.
  Warn, not deny: a model that declares `m` usually applies it itself.
* **F7a — the range text.** A discrete set `from {1, 2, 4}` is lowered to one bound per
  member, and `bounds_source` rendered it *from 1 from 2 from 4*, which is what ngspice's
  out-of-bounds message quoted. The members are gathered back into their set — *range
  from {1, 2, 4}*, *(value 1.5; range from {0.5, 1.0, 2.0})* — and intervals keep their
  form.
* **F7f — `noise_table` with a frequency twice** compiled and the runtime held the first
  power everywhere. Two literal entries at the same frequency are refused, naming it,
  under `noise_table` and `noise_table_log` alike; an unsorted table stays legal (the
  runtime orders it) and E-396's odd-length and negative-power checks are unchanged.
* **F7h — `case (s) endcase`** with no item compiled; the grammar requires at least one.
  It is a syntax error reported at the `endcase`, through a new `EmptyCase` variant on
  the parser and syntax error enums. A `default` placed first, nested and single-item
  cases are unaffected.
* **F8 — withdrawn.** A string operating-point variable is a documented design of the
  `opvar` work: `show <inst>` displays its text, and only the *vector* path (`print`,
  `$&`) refuses it — with exactly the "can not handle string value" message the hunt
  quoted, which `opvar_examples` pins as the intended clear error. A first cut of this
  enhancement refused such variables at the declaration and broke that suite; it was
  reverted.

## Verification

| check | result |
|---|---|
| `I(<a[1]>)`, `branch (<a[2]>) pb2` | compile; in a running deck the probes read 4 mA and 9 mA; `<a[5]>` refused |
| L029 | names `m`, `temp`, `dtemp`, `dt` and an upper-case `M`; not `mm`, `temperature`, `dtemp2` |
| range text | *range from {1, 2, 4}*, *(value 1.5; range from {0.5, 1.0, 2.0})*, *(value 0; range from (0:inf))* |
| `noise_table` | a duplicated frequency refused naming it; unsorted accepted; `noise_table_log` refused under its own name; odd length still refused |
| `case` | the empty one a syntax error at `endcase`; default-first, nested, single-item compile |
