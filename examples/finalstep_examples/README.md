# finalstep_examples — `@(final_step)` + analysis-phase lists (Enhancement-53)

Demonstrates the **`@(final_step)` event** — firing exactly once at the last
point of each analysis — and **analysis-phase lists** on both step events
(`@(initial_step("tran","ac"))`, LRM 5.10.2), using the committed
`openvaf-r` and `ngspice-46`.

## What was broken

- **`@(final_step)` never fired** — Enhancement-7's documented fail-safe
  no-op (firing needs "the analysis is over" knowledge the per-iteration
  eval loop doesn't have). The analyses (tran/op/dc/ac/noise) now call a new
  `OSDIfinalStep()` once on successful completion: one dedicated `eval()`
  per OSDI instance with `EVAL_FLAG_IS_FINAL_STEP` (1<<21) set at the
  converged final solution; its results are not loaded into the matrix/RHS.
- **Phase lists were silently dropped** — the AST always carried them, but
  `lower_event_control` ignored them, so `@(initial_step("ac"))` fired
  during a transient run. They now AND the step flag with the same per-name
  `analysis()` matcher (E-30), OR-ed across names.
- **`@(initial_step("ac"))` couldn't fire in an AC run** — an AC job's first
  model evaluation is its DC operating-point phase, which carried no
  `ANALYSIS_AC` flag (tran's op already mapped to `ANALYSIS_TRAN`).
  `OSDIload` now consults the running job's type and adds the analysis name
  bit (only — not the reactive `CALC_*` bits) during that op.

## Run

```
python3 verify_finalstep.py
```

Checks (23, ALL PASS): tran fires `final` exactly once at t = tstop seeing
the converged solution; op fires both `initial` and `final` (a single point
is first and last); ac/noise fire `final` once after the sweep; a dc sweep's
`final` sees the last sweep point (V = 2.0 exact); phase-qualified events
fire only in matching analyses (incl. a multi-name list); and the LRM's
classic use case — a peak tracked across the whole transient, reported
exactly once at the end (vpeak = 1.5).
