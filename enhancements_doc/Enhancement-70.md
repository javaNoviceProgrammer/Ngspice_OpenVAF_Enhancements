# Enhancement-70 — behavioral-loop audit: precise loop diagnostics

This document describes Enhancement-70: a systematic audit of the
**runtime loop statements** inside analog blocks (`for`, `while`,
`do`-`while`, `repeat`) — the simulation-time cousins of Enhancement-67's
`generate` audit. Front-end only — no OSDI/ngspice change.

## The audit (14 probe forms, all values verified numerically exact)

| feature | verdict |
|---|---|
| `for` / `while` / `do`-`while` (E-19) / `repeat(n)` | exact (sum 1..4 → 10 mS four ways) |
| nested loops | exact (3×4 → 12 mS) |
| **parameter-dependent trip counts** | exact — and a **model-card override (`n=25`) changes the count at simulation time**, the precise complement of E-67's generate restriction (structure binds at compile time, behavior at simulation time) |
| solution-dependent `while` condition (`while (acc < V(a,c)*5)`) | converges, exact |
| loops over arrays (E-14) | exact |
| iterative algorithms (Newton `sqrt(16)`, 20 iterations) | exactly 4 |
| **contributions inside loops** | accumulate (3 iterations of `I <+ V·1m` → 3 mS) |
| loops inside analog functions | exact (iterative 5!) |
| `while (0)` | body never executes |
| `break` | correctly rejected (not Verilog-A) |
| analog operator (`ddt`) inside a loop body | correctly rejected per **LRM 4.5.1** — but see below |

## The one defect: a misleading diagnostic (fixed)

An analog operator inside a **loop body** was rejected — correctly — but
the message read *"analog operator 'ddt' is not allowed in **conditions**"*:
the validator lumped loop bodies into the conditional context
(`BodyCtx::Conditional`), pointing users at the wrong construct entirely.

**Fix (`hir_ty/src/validation/body.rs` + `validation.rs`):** loops now
enter their own **`BodyCtx::Loop`** context (same restrictions, precise
reporting) via a parametrized `validate_condition_in`. The error now
reads:

```
error: analog operator 'ddt' is not allowed in loops
  = help: analog operators are not allowed inside looping statements (LRM 4.5.1)
  = help: hoist the operator out of the loop, or unroll the loop with `generate`
```

while the `if`/`case` message is unchanged.

## Examples (`analogloop_examples/`, 12 checks, ALL PASS)

`verify_analogloop.py`: [1] nine exact-conductance checks covering every
loop statement, nesting, arrays, Newton iteration, contributions-in-loops,
and function-body loops; [2] the parameter-bound override pin (default 10,
model-card 25); [3] the fixed diagnostic (names "loops", cites LRM 4.5.1,
and no longer says "conditions").

## Regression

All 64 example verify suites pass; the E-68 integration suite (now part of
the regression runner) passes 28/28; crate tests (including the dev-gated
sets) pass; the VA_TEST corpus compiles 92/92.
