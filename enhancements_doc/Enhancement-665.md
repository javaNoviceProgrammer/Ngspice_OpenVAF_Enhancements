# Enhancement-665: the diagnostic slips and run-time silences of the 2026-09-18 hunt — eleven messages that now name their subject, two deck-fixed domains that now speak, and a nesting-limit recovery that stops inventing errors

**Scope:** F11, F12, F13 and F15 of the
[bug hunt of 2026-09-18](../docs/bug_hunts/2026-09-18_openvaf-r-corners-and-run-control.md).
Compiler only: `openvaf/syntax/src/parsing.rs` and `error.rs`,
`openvaf/parser/src/{error.rs,grammar/stmts.rs,grammar/attributes.rs,grammar/expressions.rs}`,
`openvaf/syntax/src/parsing/tree_builder.rs`, `openvaf/basedb/src/diagnostics/{sink.rs,syntax_error.rs}`,
`openvaf/preprocessor/src/{processor.rs,diagnostics.rs}`,
`openvaf/hir_def/src/nameres/{collect.rs,diagnostics.rs}`,
`openvaf/hir_ty/src/validation/body.rs`, `openvaf/hir_lower/src/expr.rs`,
`openvaf/sim_back/src/{module_info.rs,diagnostics.rs}`.
`examples/hunt17diag_examples/` (new, 20 checks per solver). Handbook
[§2.4](../docs/handbook/02-verilog-a-language.md) row (L036).

**Suites:** [`hunt17diag_examples`](../examples/hunt17diag_examples/) 20 of 20
per solver, both solvers (15 of 20 fail on the E-661 binaries); `commaexpr`,
`diagslips`, `hunt3diag`, `lrmjump` unchanged; the compiler's workspace tests
green (the three sourcegen rewrites are the known drift); full sweep 530 of 530.

## What changed, item by item

**F11 — diagnostic slips.**

| was | now |
|---|---|
| `1e3n`, `0.5e`, `1meg`: *unexpected token identifier; expected 'exclude' or 'from'* — the lexer ended the number before the letters and the parser complained about the leftover in the range-clause vocabulary | a number immediately followed by an identifier is a malformed literal, reported once as a whole with its text and the LRM 2.6.2 rule (an exponent *or* a scale factor; `1meg` is SPICE's mega, Verilog-A's is `1M`); the letters become trivia so the rest parses |
| a node-array index out of range summarised *could not compile `x.va__namerange.va`* | the summary strips the elaborated-copy suffixes and names the author's file |
| `nature Qx; access = Qx;`: *'Qx' was already declared in this scope* and two knock-ons | *nature 'Qx' names its access function 'Qx' too; the access function needs a name of its own*, with LRM 3.6.1's `access = Q` example; the access is not declared, so the nature stands |
| `forever begin … end`: *expected ';'* then *'forever' was not found* | one error at the identifier: a bare identifier before `begin` is not an analog statement; the loops are `repeat`, `while`, `for` (A.6.4); the identifier sits in an error node, the block parses as the next statement |
| a non-ASCII identifier: *encountered unexpected token!* | *unexpected character(s) in the source: not a token of Verilog-A here*, over the lookalike note that already named the character |
| `(* desc= *)`: the generic expression-start list | *the attribute has no value after '='* |
| an undeclared macro reference: *has not been declared* and then *unexpected token ';'* about the hole it left | the reference leaves a synthesized `0` behind; one error, the compile fails as before |
| `(* corner="ss=0.5 %" *)`: *corner entry '%' is malformed: … there is no '='* | *a percentage or a sigma count is written without a space (`ss=+10%`, `ss=+3sigma`); the number before it was read as an absolute value* |

**F12 — run-time domain silences.** `absdelay(V(p,n), td)` with a parameter
`td = -1e-9` and `$bound_step(bs)` with `bs = -1e-9` ran without a word (the
literal forms are refused). Both now follow [E-651](Enhancement-651.md)'s rule:
a value the deck fixed is projected onto the domain and said once per accepted
point — *absdelay: the delay is -1e-09, negative (LRM 4.5.7 requires a
non-negative delay); 0 is used* and *$bound_step: the bound is -1e-09, not
positive; it is ignored and the incumbent bound stands* — while a run-time
quantity is projected in silence, since it may pass through any value on its
way to the solution.

**F13 — declaration checks.** `parameter string s = "z" from {"x", "y"}` now
draws L027 like a real or an integer would (the default is judged against the
constant set, `exclude` included); an escaped identifier that exports
`foo+bar` — which `@n1[foo+bar]` reads as a subtraction — now draws L036,
which names any character ngspice's parsers cannot take (`$` as before, `+`,
`-`, a space, …); an array element's `q[0]` and a dotted child path stay
silent, since ngspice reads those.

**F15 — the nesting-limit cascade.** A flat sum of 999 parameters trips
*expression nests too deeply* and the old recovery bumped one token and handed
the rest of the expression back to the statement parser, which read it as
declarations: *'p997' was not found*, *'p998' was already declared*. The
recovery now skips to the end of the expression — the closing bracket of the
enclosing pair, or the `;` at bracket depth zero — so the one error stands
alone.

## Withdrawn on re-check

- `` `ifdef Z 6 ``: the text after the macro name is the conditional group
  (IEEE 1364 19.4), skipped when `Z` is undefined and compiled when it is
  defined. Not a slip; pinned as expected behaviour.
- `$discontinuity(-1)`: `-1` is the LRM's limiting-discontinuity marker (the
  page-261 `spicepnjlim` diode), and [E-420](Enhancement-420.md) already refuses
  anything below it. Pinned.
- A base nature without `abstol`: LRM 3.6.1.2 calls the attribute required, but
  [E-422](Enhancement-422.md)'s suite pins the omission as legal and the round-4
  audit withdrew an error for it as a project decision, recorded in
  `hir_ty/src/validation/types.rs`. Left as it is; reversing it is a decision
  for the project, and a warning would be the middle ground.

## Verification

| check | result |
|---|---|
| `1e3n`, `0.5e`, `1meg` | one error each, the literal named, its rule in the help |
| the node-array summary | `could not compile `nodearr.va`` |
| `nature Qx; access = Qx;` | the rule named; no *already declared* |
| `forever begin … end` | one error; no *was not found* |
| `rö` | the nouned headline |
| `(* desc= *)`; `` `undef X `` then `` `X `` | one error each |
| `corner="ss=0.5 %"` | the no-space reason |
| a string default outside its set, one `exclude` names, one inside | L027, L027, none |
| `\foo+bar`, `a$b` | L036 naming `+`, L036 naming `$` |
| the 999-term sum | one error |
| `absdelay` with `td = -1e-9` from the deck; a run-time variable | the warning, 0 used, the run completes; silence |
| `$bound_step` with `bs = -1e-9` from the deck; a positive bound | the warning; none |
| the E-661 binaries on the same suite | 15 of 20 fail |

Full sweep 530 of 530 on both solvers.

## What this does not do

- `nature Qx; access = Qx;` still gets one knock-on (*expected a function but
  found nature 'Qx'*) at the access site, since the access was not declared.
- The lookalike table behind the non-ASCII message is unchanged.
- A run-time variable driven negative in `absdelay` or `$bound_step` is
  projected in silence, by E-651's rule.
