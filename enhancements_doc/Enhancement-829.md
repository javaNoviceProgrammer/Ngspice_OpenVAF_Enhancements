# Enhancement-829: a Verilog-A `$fatal` inside `@(final_step)` fails the run, and `$finish` or `$stop` there is noted

**Scope:** F13 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).

ngspice:
- `osdi/osdiload.c`: `OSDIfinalStep` keeps what its evaluations raised, and
  `OSDIfinalStepVerdict` reports it.
- `include/ngspice/osdiitf.h`: the declaration.
- `spicelib/analysis/cktdojob.c`: asks for the verdict after each analysis, the sensitivity
  analysis included.
- `frontend/com_hb.c`: `hb`, which runs outside a job, asks too.

`examples/limfinal_examples/` (new; section [1], seven checks). **ngspice only.**

**Suites:** [`limfinal_examples`](../examples/limfinal_examples/) 14 of 14 per solver (6 of the
7 checks in [1] fail on the E-828 binaries; the seventh is the `@(initial_step)` control). The
full sweep, 546 of 546.

## What was wrong

```verilog
@(final_step) $fatal(0, "...");
```

This printed `OSDI(fatal) n1: … (at the operating point)` (or `at t = 3e-09`, or `at sweep
value 1`) and nothing more:
- the analysis was not marked aborted;
- the exit status was 0;
- the script ran on.

A `$fatal` anywhere else aborts and gives exit status 1. A `$finish` or `$stop` inside
`@(final_step)` was dropped without a word.

`OSDIfinalStep` (Enhancement-53) evaluates every instance once more with the final-step flag,
and discarded what the evaluation returned. Its callers, every analysis, ignored its return
value too.

## The change

- **Recorded.** `OSDIfinalStep` collects the evaluations' return flags: a `$fatal` (or a fatal
  judged on the accepted point, Enhancement-703), a `$finish`, a `$stop`.
- **Acted on once the analysis has returned.** `OSDIfinalStepVerdict()` reports what was
  collected and clears it:
  - **A `$fatal`:**
    ```
    Error: a Verilog-A device raised $fatal in @(final_step), after the analysis had
    produced its results; the run stops here.
    ```
    It returns `E_PANIC`, so the job ends failed, as a `$fatal` anywhere else does:
    "simulation(s) aborted", `sim_status` 1, exit status 1. The analysis's results stay
    readable.
  - **A `$finish`:** a Note that the analysis had already ended.
  - **A `$stop`:** a Note that the analysis had already ended, so there is nothing to pause.
- **Where.** `CKTdoJob` asks for the verdict after each analysis function returns, which covers
  every analysis that fires the final step, `sens` included. `hb` asks after its own final
  step and sets `sim_status`.

## The checks

`limfinal_examples` [1], a module whose final step raises the task:
- `op` with `$fatal`: the error, "op simulation(s) aborted", exit status 1 (was 0); i(v1) =
  −1 mA still printed.
- `tran` and `dc`: the same, with the last point and the sweep still readable.
- `$finish`: the Note, exit status 0 (was silent).
- `$stop`: the Note, nothing to pause (was silent).
- `$fatal` in `@(initial_step)` (control): aborts as before.
- `hb 1meg 4` with `$fatal` in the final step: the error and exit status 1 (was 0).
