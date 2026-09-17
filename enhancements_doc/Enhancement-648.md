# Enhancement-648: an event control under a non-constant condition is refused (2026-09-16 hunt F4)

**Scope:** F4 of the
[2026-09-16 hunt](../docs/bug_hunts/2026-09-16_openvaf-r-functions-conversions-and-events.md).
Compiler: `openvaf/hir_ty/src/validation/body.rs` (the `EventInConditional`
check covers every event form under a non-constant `if`/`case`, not only
`cross`/`above`; `event_form_name`), `openvaf/hir_ty/src/validation.rs` (the
LRM 5.8 sentence for the new cases). New suite
[`eventcond_examples`](../examples/eventcond_examples/) (15 checks per
solver). **Compiler side.**

**Suites:** `eventcond_examples` 15 of 15 per solver, both solvers (9 of 15 on
the E-644 compiler); `events`, `eventaudit`, `crossabove`, `timer` and every
other event suite green; workspace `cargo test` green; full sweep 521 of 521.

## What was wrong

LRM 5.8: *"Event control statements (e.g.: timer, cross) cannot be used inside
conditional statements unless the conditional expression is a constant
expression."* The compiler enforced LRM 5.10.3.1's narrower rule for
`cross`/`above` (the events audit's `EventInConditional`, which also reaches
into `repeat`/`while` loops as that clause says) and nothing for
`initial_step`, `final_step` and `timer`:

```verilog
integer k;
analog begin
  if (V(p,n) > 0) @(initial_step) k = k + 1;
  @(final_step) $strobe("k=%d", k);
  I(p,n) <+ V(p,n);
end
```

compiled clean and printed `k=0` at an operating point where V(p,n) = 1: the
initial-step event is delivered on the first Newton iteration, when the node is
still at the solver's initial guess of 0, so the condition was false at exactly
that moment and the block never ran. Under `if (1)` or a parameter condition it
ran (`k=1`); a `timer` under a node condition fired on the iterations where the
condition happened to hold. The outcome was whatever the solver's iteration
state made of the condition, which is the reason the LRM has the rule.

## What changed

In the `Stmt::EventControl` arm of body validation, under `BodyCtx::Conditional`
— which the walk enters only when an `if`/`case` condition is non-constant; a
literal, a parameter, a string-parameter compare, `analysis()` and
`$temperature` do not switch it — every event form is now reported, not only
the monitored ones: `@(initial_step) is not allowed inside a conditional`, with
the LRM 5.8 sentence, the first-guess explanation and the recommended shape
(the event at the top level, the condition inside its body). The `cross`/`above`
cases keep their 5.10.3.1 message and their loop rule. A runtime loop is not a
conditional statement — 5.8 names none, and a `for` over an integer variable
is a non-constant loop in this walk — so an `initial_step` or a `timer` inside
one stays allowed. `event_form_name` spells every form for the message
(`@(timer)`, `@(final_step)`, …; an `or` list is "an event control").

## Verification

| check | result |
|---|---|
| `@(initial_step)` / `@(timer)` under `if (V(p,n) > 0)`; `@(final_step)` under `case (V(p,n) > 0.5)` | refused, LRM 5.8 sentence, one error each |
| under a module variable written from `V(p,n)`; under a constant `if` nested in a non-constant one; an `initial_step or final_step` list | refused |
| `@(cross)` under `if (V(p,n) > 0)`; in a `while` loop | refused with 5.10.3.1's own message, as before |
| under `if (1)`, a parameter, a string-parameter compare, `analysis("dc")`, `$temperature > 300` | accepted, the event fires (k = 1) |
| a runtime `for (i = 0; i < 2; …)` around the event | accepted, k = 2 |
| the recommended shape, `@(initial_step) if (V(p,n) > -1) …` | accepted, k = 1 |
| workspace `cargo test` (verilogae and `sourcegen` excluded as before) | green, no generated file rewritten |
| `eventcond_examples` | 15 / 15 per solver, both solvers; 9 / 15 on the E-644 compiler |
| full sweep | 521 of 521 — no model in the corpus had an event under a non-constant condition |

## What this does not do

A `while` loop whose bound depends on a node voltage, with a global event or a
timer inside, is still accepted: the LRM forbids only `cross`/`above` there
(5.10.3.1), and 5.8's rule is about conditional statements. The hunt's F5 and
the rest of the list are separate enhancements.
