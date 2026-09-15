# Enhancement-635: an integer parameter's real range bounds are compared as reals

**Scope:** F1 of the
[2026-09-14 hunt](../docs/bug_hunts/2026-09-14_openvaf-r-parameters-arrays-and-hierarchy.md).
`parameter integer k from (0.5:2.5]` admits 1 and 2, and the run-time check
refused 1 and accepted 3. Compiler: `openvaf/hir_ty/src/inference.rs` (a real
bound of an integer parameter keeps its type; `inf` there is the real
infinity), `openvaf/hir_lower/src/parameters.rs` (the comparison is made in
the bound's domain, the parameter's value cast to a real once),
`openvaf/hir_def/src/item_tree/lower.rs` (a range no integer satisfies is
refused at compile time). New suite
[`intrange_examples`](../examples/intrange_examples/) (12 checks per solver).
**Compiler side.**

**Suites:** `intrange_examples` 12 of 12 per solver, both solvers;
`paramrange`, `instdep`, `rangeguard`, `osdiparam`, `paramarray`, `paramset`,
`paramsetlrm`, `localparam`, `paramgiven`, `strparam` green; the `hir_ty`,
`hir_lower` and `hir_def` crate tests green; full sweep 508 of 508.

## What was wrong

A parameter's body is its default and every `from`/`exclude` bound, and type
inference gave every one of those entry statements the parameter's declared
type — right for the default (a real default of an integer parameter rounds,
LRM 3.4.1), wrong for a bound: the cast rounded `0.5` to 1 and `2.5` to 3 (half
away from zero) before the integer comparison was emitted. So:

| declared | legal | the run-time check accepted |
|---|---|---|
| `from (0.5:2.5]` | 1, 2 | 2, 3 |
| `from [1.5:2.5]` | 2 | 2, 3 |
| `from (1.5:2.5)` | 2 | nothing |
| `from [0:10] exclude 2.5` | 0 … 10 | 0 … 10 except 3 |
| `from [0:inf)` | 0 … 2147483647 | 0 … 2147483646 (`inf` was `i32::MAX`, and the bound is exclusive) |
| `from (-inf:inf)` | every integer | every integer but −2147483648 |

The compile-time side never rounded: E-399's emptiness check and E-532's L027
(the default against its own range) fold the bounds as reals, so `parameter
integer k = 3 from (0.5:2.5]` was warned as violating its range and then
accepted at setup, while `k = 1` passed the compile-time check and was refused
at setup. The E-558 range text in the message printed the real bounds the check
had not used.

## What changes

* **`hir_ty`:** for an integer parameter, the bound statements (every entry
  after the default) are inferred with the cast suppressed when the bound is a
  real, and `inf`/`-inf` there are typed real. The default still converts to
  the declared type. A bound that is an integer expression is untouched.
* **`hir_lower`:** `check_param` asks each bound whether it is a real (a `-inf`
  is a unary minus over the literal, whose own type inference never records, so
  the literal under it is consulted); if any is, the parameter's value is cast
  to a real once, in the block that dominates every comparison, and those
  bounds are compared with the real opcodes — an integer bound keeps the
  integer comparison, so a range like `from [0:inf)` mixes the two. An `i32`
  is exact as an `f64`, so nothing is lost. The informational min/max path
  (not built by the OSDI backend) converts a real bound back to the
  parameter's type so its slot keeps that type.
* **`hir_def`:** the emptiness check (E-399) asks the question the run-time
  check will now ask: for an integer parameter, does any integer lie in the
  range? `from (1.5:1.9)` and `from (2:3)` are refused as ranges "which no
  value can satisfy … the parameter is an integer and no integer lies between
  2 and 3 with these bounds"; `[2:3)`, `(1.5:2.5]` and a real parameter's
  `(2:3)` compile as before.

E-546's per-instance judgement (`from (0.5:w]` with an instance `w`), E-555's
default-against-a-moved-range, E-461's sets (`from {1.5, 2, 3}`: 1.5 no longer
rounds onto 2), array parameters (per element) and `exclude` with a
parameter-referenced bound all go through the same `check_param` and are
pinned by the suite.

## Verification

| check | result |
|---|---|
| `(0.5:2.5]` | 1, 2 accepted; 0, 3 refused |
| `[1.5:2.5]`, `(1.5:2.5)` | only 2 |
| `[0:10] exclude 2.5` | 2, 3, 10 accepted; 11 refused |
| `[0:inf)`, `(-inf:inf)`, `[-inf:0]` | 2147483647 and −2147483648 accepted at their ends |
| `(0.5:hi]`, `(0.5:w]` (instance `w`), `'{1,2} from (0.5:2.5]`, `{1.5, 2, 3}`, `exclude x exclude [7.5:inf)` | as declared, per parameter, instance and element |
| `(1.5:1.9)`, `(2:3)` on an integer | refused at compile time, the reason named; `[2:3)`, `(1.5:2.5]`, a real's `(2:3)` accepted |
| L027 | `k = 3 from (0.5:2.5]` warned, `k = 1` not — and setup now agrees |
| `intrange_examples` | 12 / 12, both solvers |
| full sweep | 508 of 508 |
