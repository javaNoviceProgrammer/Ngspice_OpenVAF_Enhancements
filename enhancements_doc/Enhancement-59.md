# Enhancement-59 — LRM-corner probe follow-up: event OR lists, `$realtime`, port concatenation, recursion diagnostics

This document describes the changes made to **OpenVAF-r** in the `version11/`
directory following a fresh LRM-corner probe battery (16 never-exercised
Annex-C constructs). Front-end only — no OSDI/ngspice change.

## The probe battery

16 small models covering LRM corners no previous enhancement had exercised.
**12 were validated as already correct** (several at runtime, exact):
away-from-zero real→integer rounding, `$vt(300)`, aliasparam +
`$param_given` through the alias, string-parameter `case` + `.model` string
override, `above()` in DC, integer `min`/`max`/`abs`, integer function
output args, grounded (single-node) branch declarations, parameter-dependent
`laplace_nd` coefficients, `$mfactor` reads, `branch.potential.abstol`, and
`ddx` w.r.t. a flow probe.

**4 gaps** were found and fixed:

| gap | before |
|---|---|
| event OR lists `@(a or b)` (LRM 5.10.3) | parse error at `or` |
| `$realtime` (LRM 9.7.2) | unknown system function |
| port-connection net concat `u1({a,c})` (LRM 6.5) | whole `{a,c}` text bound to every bit → "expected value but found net reference" |
| analog-function recursion | direct: misleading "expected a function but found variable"; **mutual (`f1→f2→f1`): compiler stack overflow** |

## 1. Event OR lists

`@(cross(...) or cross(...))`, `@(initial_step or timer(t))` — any mix of
members in one list.

- **tokens**: new `OR_KW` keyword (`or` was already reserved).
- **parser** (`grammar/stmts.rs`): `event_stmt` loops over `or`-separated
  units; each unit is either an `initial_step`/`final_step` (with optional
  phase strings) or an event expression.
- **hir_def**: new `Event::Or(Box<[Event]>)` variant; `collect_event_stmt`
  segments the syntax children on `OR_KW` tokens and builds one `Event` per
  unit (a malformed unit degrades the whole event to an unconditional body,
  as before). The child-expr walker recurses through `Or` via a
  `&mut dyn FnMut` inner fn (a generic closure would monomorphize
  infinitely).
- **hir_lower** (`stmt.rs`): `lower_event_fired` lowers each member to its
  "fired" boolean and folds them with the file's **`bool_or`** helper
  (`make_select`-based). A raw `ior` instruction is wrong here: the members
  are `i1` values that can const-fold, and MIR const-eval has no Bool arm
  for `ior` — it ICEs (`invalid operation ior Bool(true) Bool(true)`).

Runtime check: with a crossing pair OR'd, the counter equals the **sum** of
the two single-event counters exactly, and `@(initial_step or timer(0.55u))`
fires exactly twice in a 1 µs transient.

## 2. `$realtime`

In the analog context `$realtime` is the simulation time in seconds —
identical to `$abstime` (the `timescale`-scaled digital flavor is
meaningless in a continuous-time solver). New builtin lowered to the same
`ParamKind::Abstime`. Verified `$realtime − $abstime ≡ 0` through a
transient. (Gotcha re-confirmed: `hir_ty/src/builtin/generated.rs` holds a
`BUILTIN_INFO` array whose length is hardcoded — appending a builtin without
bumping `112usize → 113usize` is an index-out-of-bounds ICE. Signature
tables remain the recurring defect source.)

## 3. Net concatenation in port connections

`pcleaf u1({a, c});` onto `inout [1:0] p` — handled entirely in the E-5
elaboration pass. `PortConn::net()` already returned an `ast::Expr`, and
E-34 made `{...}` a real `ConcatExpr`, so the pieces existed; new
`bind_port_actual` dispatches a concat actual to `bind_port_concat`:

- each element contributes one bit (scalar net, bit-select, ...) or — when
  it names a same-scope bus used whole — **all** of that bus's bits in *its*
  declared msb→lsb order;
- the flattened bit list maps onto the port in the **port's** declared
  msb→lsb order (leftmost element = port msb), so `[1:0]` and `[0:1]`
  declaration styles both connect as written;
- a bit-count/width mismatch (or a multi-element concat on a scalar port)
  is a hard error, collected in a new `port_conn_errors` sink (rendering
  has no error channel) and bailed after rendering, like
  `implicit_conflicts`.

Works positionally and named (`.p({b[1], b[0]})`), nested through instance
levels. Runtime check: two concat-connected 1 kΩ paths in parallel + 1 kΩ
series → exactly 2 V / 1.5 kΩ = 1.3333 mA.

## 4. Recursion diagnostics

The LRM forbids analog-function recursion; the compiler now says so.

- **Direct** (`fact` calling `fact`): inside a function its own name
  resolves to the return variable, so the call landed in the "expected a
  function but found variable 'fact'" fallback. `infere_fun_call` now
  recognises `owner == called name` and emits a dedicated
  `RecursiveFunctionCall` diagnostic: *"analog function 'fact' cannot call
  itself: recursion is not allowed"* with an LRM 4.7 help note.
- **Mutual** (`f1→f2→f1`): this **crashed the compiler** (stack overflow in
  the recursive inliner) — found by a sanity check while testing the direct
  case. Fix: a call-graph cycle check in `BodyValidationDiagnostic::collect`
  for function bodies — DFS from each user-function call through the
  callees' own (independently inferred, so salsa-cycle-free)
  `resolved_calls`; a path back to the owner reports the full chain:
  `info: call cycle: f1 -> f2 -> f1`. Legitimate diamond call chains
  (`f→g→h`, `f→h`) are unaffected.

## Examples (`lrmcorner_examples/`, 9 checks, ALL PASS)

`verify_lrmcorner.py`: [1] OR-list counter ≡ sum of single-event counters +
`initial_step or timer` fires twice; [2] `$realtime` tracks `$abstime`
exactly; [3] port-concat op current exact (both concat forms); [4] direct
and mutual recursion are clean errors (the mutual one names the cycle);
[5] concat width mismatch rejected; [6] `lrmpin_demo.va` — self-checking
bitmask module (E-37 technique) pinning 8 runtime-checkable validated
corners, score 255/255; [7] compile-only pins (gnd branch, ddx-flow,
above-DC, laplace-param, integer fn outputs).

Note: the corner-pin's `$vt(300)` check uses a 1e-7 tolerance — the
compiler's internal `$vt` uses newer CODATA constants than the LRM-1998
values in the shipped `constants.vams` (difference ≈ 3e-8). Not a defect.

## Regression

All version11 example verify suites pass; crate tests (tokens, parser,
syntax, hir_def, hir, hir_ty, hir_lower, sim_back, osdi) pass.
