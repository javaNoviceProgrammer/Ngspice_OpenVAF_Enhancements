# Enhancement-820: a `.dc` sweep of a temperature or an OSDI parameter carries the model's variables from point to point, and `@(final_step)` sees the last point

**Scope:** F4 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).

openvaf:
- `hir_lower/src/lib.rs`: a new `ParamKind::IsAnalysisStart`.
- `hir_lower/src/state.rs`: `insert_var_init` initialises the variables on it, not on
  `IsInitialStep`.
- `osdi/src/eval.rs`: `EVAL_FLAG_SWEEP_CONTINUES` (bit 22); `IsAnalysisStart` is the initial
  step without it.
- `osdi/src/inst_data.rs`, `openvaf/src/lib.rs`, `verilogae/src/back.rs`: the new kind in their
  matches.

ngspice:
- `include/ngspice/osdiitf.h`: `OSDIdcSweep` and its three phases.
- `osdi/osdisetup.c`: the phase. Setup and the temperature pass mark an instance
  `sweep_continues` when they clear its `has_evaluated` at a later sweep point.
- `osdi/osdidefs.h`: the mark and `EVAL_FLAG_SWEEP_CONTINUES`. `osdi/osdiload.c`: both
  evaluation paths pass the flag with the initial step.
- `spicelib/analysis/dctrcurv.c`: the sweep sets the phase. `@(final_step)` fires before the
  restore, not after it.

`examples/sweepstate_examples/` (new; section [1], nine checks).

**Suites:** [`sweepstate_examples`](../examples/sweepstate_examples/) 18 of 18 per solver (7 of
the 9 checks in [1] fail on the E-819 binaries; the other two are controls: the value the
initial step computes, which already followed the sweep, and a source sweep). The workspace
tests (only the three known sourcegen drift failures). A BSIM4 comparison. The full sweep, 543
of 543.

## What was wrong

A module that counts its initial steps and reports in its final step:

| analysis | the counter at each point | `@(final_step)` sees |
|---|---|---|
| `dc v1 0 2 1` | 1 (one initial step) | V = 2, the last point |
| `dc temp 0 100 50` | 1, 1, 1 | 300.15 K, the netlist's, not 373.15 |
| `dc @n1[p] 1 3 1`, `dc @tm[q] 1 3 1` | 1, 1, 1 | p = 1 (q = 1), not 3 |

A temperature or OSDI-parameter point re-runs the device's temperature pass, and that pass
clears the instance's "evaluated" mark (Enhancement-7). So the next evaluation fires
`@(initial_step)` again. Re-firing is right. LRM 5.2.1 re-executes initialisation when a sweep
changes a parameter it reads. The corpus's BSIM4 does all of its temperature and parameter
preprocessing (lines 2104–8921) inside `@(initial_step)`. Fired once, every later point would
run on the first point's values.

Two things went wrong with it:
- **The variables were initialised with it.** The compiler sets each variable to its declared
  value on the initial step (Enhancement-7's `insert_var_init`). A counter read 1 at every
  point, where a source sweep carried it. LRM 4.6.2 says the values at the end of one dc point
  are the starting values for the next. They are re-initialised only at the start of a new
  analysis.
- **`@(final_step)` ran after the restore.** The sweep put the temperature or parameter back
  first, which re-ran the temperature pass. The final step then evaluated at the netlist's
  value. A `$finish` at a mid-sweep point ended the same way. Table 5-1 puts the final step on
  the last point.

## The change

- **A second flag.** `EVAL_FLAG_SWEEP_CONTINUES` goes with the initial step when a dc sweep
  re-fires it at a later point:
  - the `@(initial_step)` blocks run;
  - the variables keep the values of the previous point.

  The compiler initialises variables on `IsAnalysisStart`, which is the initial step without
  the flag. Every other user of the initial step is unchanged: the event, an `analog initial`
  block, `above`/`cross`/`timer` and a `$table_model` capture.
- **The sweep's phase.** `DCtrCurv` tells the OSDI layer where it stands:
  - `FIRST` until the first point is solved;
  - `LATER` from then on, and on a `resume`;
  - `OFF` before its restore, and on every return.

  Setup and the temperature pass mark an instance only in `LATER`. The first point is the
  analysis's start, so an op after a sweep starts its variables again.
- **The final step first.** At the end of a sweep, and at a `$finish`, `OSDIfinalStep` runs
  before the restore. An abandoned sweep (a refused point, Enhancement-427) still fires it
  after the restore. The instance then holds the value it refused.

## The checks

`sweepstate_examples` [1]. The module's counter is declared `integer n = 10`.
- `dc temp 0 100 50`: an initial step at each point, the counter 11, 12, 13 (was 11, 11, 11).
  The conductance the initial step computes follows the temperature: i(v1) = −1 mA·T/300.15.
  The final step runs once, at 373.15 K (was 300.15).
- `dc @n1[p] 1 3 1` (an instance parameter) and `dc @tm[q] 1 3 1` (a model parameter): 11, 12,
  13; i(v1) = −p mA, −q mA; the final step at 3 (was 1).
- `dc v1 0 2 1`: one initial step, the final step at V = 2 (control).
- `dc v1 0 1 1 temp 0 100 100`: an initial step per temperature, 11 then 12; the final step at
  373.15 K and V = 1.
- An `op` after the temperature sweep: the counter starts again at 11, at 300.15 K.
- `$finish` at the 50 °C point: the final step at 323.15 K (was 300.15).

BSIM4 (`integration_tests/BSIM4/bsim4.va`) gives the same drain current, to ten digits, as on
the E-819 binaries under each of these:
- `dc temp -40 125 55`;
- `dc @no[l] 1u 3u 1u`;
- `dc vg 0.4 1.2 0.4 temp 0 100 100`;
- an op.

## Limits

- A model compiled before this enhancement ignores the new flag and initialises its variables
  at every point, as before. It does get the final-step fix, which is in ngspice. Recompile
  it to carry its variables.
- After `$stop` in a sweep, `resume` solves the paused point again and records it twice. That
  is unchanged by this enhancement.
