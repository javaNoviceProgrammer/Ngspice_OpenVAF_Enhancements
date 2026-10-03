# Enhancement-783: a hung or runaway suite can no longer take a CI runner down — the sweep stops whole process trees on Windows, caps memory on macOS and Windows, names what a timed-out suite was running, bounds itself in time, and a smoke step times one compile and one simulation first

**Scope:** examples only. `examples/run_regression.py` (`_ps_group_procs`, `_WinJob`, `_win_procs`,
`_timeout_report`, `run_one`'s limit and stop, `NG_SWEEP_BUDGET_S`, the trace phase),
`examples/_setup.py` (the trace announces a run before it starts), and
`.github/workflows/build-binaries.yml` (a smoke step before each sweep, the sweep budget). From
CI runs 37058874987 and 37074374508.

**Suites:** the full sweep on macOS, 536 of 536; the new paths exercised on macOS (below).

## What happened

Two CI runs in a row lost their Windows job in the regression step. In 37058874987 the step was
still running after two and a half hours (the sweep alone had taken 22 minutes the run before);
in 37074374508 it ran past its own 180-minute limit, and GitHub then reported that the hosted
runner had lost communication with the server -- as it did for the macOS Intel job of the same
run, partway through its sweep. Neither job uploaded a log: what hung, or what starved the
machine, is unknown. Four gaps let one bad suite take a whole job, and its evidence, with it:

1. **A timed-out suite's children survived on Windows.** `run_one` stopped a suite after 20
   minutes with `p.kill()`, which ends the suite's Python process alone; a hung `ngspice.exe` or
   `openvaf-r.exe` under it kept running, and the next timeout left another.
2. **No memory cap outside Linux.** E-773's watchdog reads `/proc`; on macOS and Windows a suite
   could take the runner's memory, which is how the linux-arm runner was lost before E-773.
3. **The trace phase re-ran every failed suite with the full 20 minutes**, after the sweep had
   already waited that long for each one that hung -- a handful of hung suites outlasts a
   180-minute step on their own.
4. **A run that never returned left no trace.** E-777's trace records a run when it finishes.

## The change

- **Windows: a job object per suite.** Each suite runs in its own job: a stop terminates the job,
  so every process the suite started ends with it (`taskkill /F /T` where the job cannot be
  made), and the job's committed memory is capped at `NG_SUITE_JOB_MEM_MB` (one and a half times
  `NG_SUITE_MEM_MB`, 6144 MB by default; committed memory runs above the resident set the other
  watchdogs measure). A suite that reached the cap is reported as MEMORY.
- **macOS: the watchdog reads the process group with `ps`** every five seconds; the cap,
  report and stop are E-773's.
- **A TIMEOUT names what was still running**: the command line and memory of every process left
  in the suite's group or job, at the head of `_failures/<suite>.log`.
- **`NG_SWEEP_BUDGET_S` bounds the sweep.** Past it no suite starts (NOT RUN, listed with the
  failures) and a running one is stopped as a TIMEOUT. Both CI sweep steps set 9000 s, inside
  their 180-minute limit, so the summary and the logs are always written and uploaded.
- **The trace phase** skips suites that never ran, gives each re-run 300 s, and does not start
  once the budget is spent.
- **The trace announces each run before it starts** (`=== start N`, its arguments and deck): a
  run that hangs is the last start with no `=== run N` after it.
- **A smoke step before each sweep** compiles one resistor and runs one operating point, timed,
  with a five-minute limit and without failing the job: a compiler or simulator that hangs on
  the runner shows within minutes, in a log that is still being written.

## Verification (macOS)

- A six-second budget over four suites: one TIMEOUT whose report lists the suite's processes
  (its Python and the running ngspice), no process left behind afterwards.
- A one-second budget: one TIMEOUT, two NOT RUN, no trace phase.
- `NG_SUITE_MEM_MB=40` on benchmark: stopped as MEMORY, its processes listed from `ps`.
- A traced suite: 58 starts, 58 finishes, paired by number.
- The smoke step's script, run against `bin/macos/apple-silicon`: `i(v1) = -1.00000e-03`.
- The full sweep, 536 of 536.

## Limits

- The Windows job object and `_win_procs` (PowerShell's `Get-CimInstance`) run only on the
  Windows CI job; any failure to create the job leaves the suite running as before, unguarded,
  with the `taskkill` stop.
- This does not say what hung on Windows or what took the macOS Intel runner; it is so that the
  next run says it.
