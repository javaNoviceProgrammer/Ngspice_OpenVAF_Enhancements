# Enhancement-19 — `do ... while` loop

This document describes the source-code changes made to **OpenVAF-r** in the
`version11/` directory to implement the Verilog-AMS **`do ... while`** loop,
previously a parse error (`do` was lexed as an identifier). It is the one loop
construct OpenVAF didn't support — `for`, `while`, and `repeat` already worked.

`do <statement> while (<condition>);` executes its body **once before** the
condition is first tested (a post-test loop), so the body always runs at least
once. Verified end-to-end through ngspice — see `examples/dowhile_examples/`.

## Changes

The feature threads a new statement kind through the whole front-end, mirroring
`while` at each stage:

- **Token / syntax kind** (`tokens/src/parser/generated.rs`) — a `do` keyword
  (`DO_KW`) and a `DO_WHILE_STMT` node kind, wired into `is_keyword`,
  `from_keyword` (`"do"`), the display table, and the `T!` macro. (`SyntaxKind`
  is `#[repr(u16)]` with a bounds-checked `from_u16`, so adding variants renumbers
  consistently.)
- **Parser** (`grammar/stmts.rs`) — `DO_KW` added to the statement token sets and
  dispatch; `do_stmt` parses `do <stmt> while ( <expr> ) ;`.
- **AST** (`veriloga.ungram`, generated `nodes.rs`) — a `DoWhileStmt` node
  (`body(): Stmt`, `condition(): Expr`) added to the `Stmt` enum, its `can_cast`,
  `cast`, `syntax`, and `From` impls.
- **HIR** — `hir_def::Stmt::DoWhile { cond, body }` (with the expr/stmt walkers
  and `body/lower` mapping the AST node), the pretty printer, `hir_ty` condition
  inference and validation, and the elaborated `hir::Stmt::DoWhile` produced by
  `get_stmt`.
- **Lowering** (`hir_lower/stmt.rs`) — `lower_do_while`: like `lower_loop`, but the
  body block is entered unconditionally and the condition is tested at the end of
  each iteration. The body block is the loop header (both the entry edge and the
  back-edge from the condition), so it is sealed last for correct SSA.

## Verification

- `examples/dowhile_examples/verify_dowhile.py` — a `do` loop reports its iteration count
  as a gain; across the loop count `n` (overridden per `.model`) the count equals
  `max(n, 1)`, and in particular **`n = 0` still runs the body once** (count = 1),
  the defining post-test behaviour. `ALL PASS`.
- Ad-hoc: a `do`-loop that iterates a fixed number of times, one whose condition
  is initially false (body runs exactly once), and a single-statement body (no
  `begin ... end`) all simulate correctly.
- The `tokens`/`parser`/`syntax`/`hir_def`/`hir_ty`/`hir`/`hir_lower` unit-test
  suites pass with no regressions; every prior example folder still compiles and
  simulates with unchanged results.
