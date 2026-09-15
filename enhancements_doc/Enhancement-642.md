# Enhancement-642: a literal or computed seed for the analog random functions (IHP hunt A2)

**Scope:** A2 of the
[2026-09-15 IHP SG13G2 hunt](../docs/bug_hunts/2026-09-15_ihp-sg13g2-paramset-library.md)
— `$rdist_normal(7, 0, 1)` and `$rdist_normal(seed + 3, 0, 1)` were refused.
Compiler: `openvaf/hir_ty/src/builtin.rs` (the seed slot of `$arandom`,
`$dist_*` and `$rdist_*` is `Val(Integer)`), `openvaf/hir_ty/src/validation/body.rs`
(the enclosing loops' write sets; the L019 draw-in-a-loop lint skips a seed
the loop changes), `openvaf/hir_ty/src/validation.rs` (L019's help line).
Docs: handbook §2 random row, compliance §7.3. New suite
[`seedexpr_examples`](../examples/seedexpr_examples/) (7 checks per solver).
**Compiler side.**

**Suites:** `seedexpr_examples` 7 of 7 per solver, both solvers; the
workspace `cargo test` green; full sweep 515 of 515.

## What was wrong

LRM Syntax 9-8 and 9-9:

```
analog_random_seed ::= integer_variable_identifier | reg_variable_identifier
                     | time_variable_identifier | integer_parameter_identifier
                     | [ sign ] decimal_number
seed ::= integer_variable_identifier | integer_parameter_identifier | [ sign ] decimal_number
```

The signature table admitted the first two forms only (`Var(Integer)` and
`Param(Integer)` variants of every distribution function), so a literal was

```
error: type mismatch: expected integer variable reference or integer parameter ref but found integer literal
```

— in the analog block as well as in a paramset — although the LRM's own
§6.4.1 example seeds with literals (`$rdist_normal(1,0,1n,"global")`). The
IHP corner modules go one step further, `$rdist_normal(seed + 3, 0, 1,
"global")`, a computed seed the LRM's grammar does not spell but gnucap
accepts. The requirement for an lvalue came from the LRM's inout seed, which
the compiler does not implement: under Enhancement-10 a draw is a pure
function of the seed's *value* and the call site, and the seed is never
written back — so nothing needs a reference, and any integer expression can
serve.

## What changed

- **Signatures.** The seed slot of `$arandom` and of every `$dist_*` /
  `$rdist_*` signature is `Val(Integer)`; the `_CONST_SEED` duplicates that
  existed only to admit a parameter are gone. A variable, a parameter, a
  literal, a negative literal and an expression all fit; a real seed is
  refused the way any integer argument refuses a real ("expected integer
  value but found real literal"). `$random` keeps `Var(Integer)`: Syntax
  9-8's `random_seed` is a variable only — it is the Verilog-2001 function,
  `$arandom` the analog one that added the constant forms.
- **L019 `rng_in_loop`** (Enhancement-395: "inside a loop draws the same
  number every iteration") now asks whether the *seed* changes with the
  loop. The validator keeps the write set of each enclosing runtime loop
  (its body and a `for`'s increment, collected as `check_loop_termination`
  collects them) and a draw whose seed reads a name some enclosing loop
  writes — `seed + i`, or a variable the body advances — is a fresh draw per
  iteration and is not reported; a seed the collector cannot judge (a user
  function call in it) gets the benefit of the doubt. A literal, a
  parameter or a loop-invariant variable is the case the lint exists for and
  is still reported, with a help line that now names the seed route first:
  "give it a seed that changes with the loop (`$rdist_normal(seed + i,
  ...)`)".

## Verification

| check | result |
|---|---|
| `$rdist_normal(7, 0, 1)`, `(-5, 0, 1)`, `(seed + k, 0, 1)`, `$arandom(7)`, `$dist_uniform(3, 1, 6)` | compile; the last two integral, the draw in [1, 6] |
| the literal 7 in two instances | the same number (a draw is a function of seed and call site) |
| `seed + k` at seed = 4, k = 1 against `seed` at 5, same call site | the same number; 4 + 2 a different one |
| `for (i…) s = s + $rdist_normal(seed + i, 0, 1)` | ten draws, nine changes between consecutive iterations, no L019; the sum differs from the `seed + 1` loop's, which draws one number ten times (zero changes) and is warned with the new help |
| a seed variable the loop advances (`sd = sd + 1`) / one it never writes | not warned / L019 |
| twelve consecutive seeds at one call site | twelve distinct N(0, 1) draws; the values reproduce from a Python transcription of `osdi_rng_normal` |
| `$rdist_normal(1.5, …)` / `$random(7)` | refused: "expected integer value but found real literal" / "expected integer variable reference but found integer literal" |
| IHP `cornerRES.va` (`res_stat`, `res_mm`) through the fold | the seed errors are gone; what remains is E-545's "random draw is not allowed in constants", the statistical route the hunt's *Features* 2 describes |
| `cargo test -p hir_ty` and the workspace suite | green (no UI golden carried the old wording) |
| `seedexpr_examples` | 7 / 7 per solver, both solvers |
| full sweep | 515 of 515 |
