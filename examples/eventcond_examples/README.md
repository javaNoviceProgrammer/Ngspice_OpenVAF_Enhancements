# eventcond_examples — an event control under a non-constant condition is refused (Enhancement-648)

Fifteen checks per solver, run under both KLU and Sparse by `_setup.check_both_solvers`.

LRM 5.8: "Event control statements (e.g.: timer, cross) cannot be used inside
conditional statements unless the conditional expression is a constant expression."
Only `cross`/`above` were checked (LRM 5.10.3.1's own rule); an `initial_step`,
`final_step` or `timer` under `if (V(p,n) > 0)` compiled without a word, and whether
its block ever ran depended on the solver's first guess.

Refused, with the LRM 5.8 sentence and one error each: `@(initial_step)` and
`@(timer)` under `if (V(p,n) > 0)`, `@(final_step)` under `case (V(p,n) > 0.5)`, an
event under a module variable written from a node voltage, under a constant `if`
nested in a non-constant one, and an `initial_step or final_step` list; `@(cross)`
keeps 5.10.3.1's own message under a conditional and inside a loop. Accepted, with the
event firing: a literal, a parameter, a string-parameter compare, `analysis()` and
`$temperature` conditions; a runtime `for` loop with constant bounds (5.8 names
conditional statements only); and the recommended shape, the event at the top with
the condition inside its body.

```bash
python3 examples/eventcond_examples/verify_eventcond.py
```
