# Enhancement-653: `exit` is a second name for `quit`

**Scope:** `src/frontend/commands.c` (an `exit` entry beside `quit` in the ngspice and
the nutmeg command tables, both bound to `com_quit`), `src/frontend/com_sweep.c`
(`sw_analysis_is_destructive`: `exit` in the refused list beside `quit`),
`examples/exitcmd_examples/` (new, 10 checks per solver); handbook
[§3.11](../docs/handbook/03-ngspice-workflows.md). **ngspice only.** Requested by the
user.

**Suites:** [`exitcmd_examples`](../examples/exitcmd_examples/) 10 of 10 per solver,
both solvers (9 of 10 fail on the E-652 binary); `sweepanalysis`, `carddefault`,
`probeblock` unchanged; full sweep 526 of 526.

## What was asked

Whether a `.control` block may end ngspice with `exit`. It could not: `exit` was no
command at all, so

```
.control
op
exit
print v(out)
.endc
```

printed `exit: no such command available in ngspice` and went on with the next line —
in batch mode with everything after it. The command that leaves ngspice is `quit`. The
user asked for `exit` as a second name for it.

## What changed

- **`commands.c`:** an `exit` entry follows `quit` in `spcp_coms` (ngspice) and
  `nutcp_coms` (nutmeg), with the same handler, argument shape and flags, and the help
  text "Quit ngspice (the same as quit)". Being the same function, `exit` takes what
  `quit` takes: an integer is the process's exit status (`exit 3`), and `noask` skips
  the "Are you sure you want to quit (yes)?" question that `set askquit` raises when a
  simulation is still in progress or a plot has not been written. In the shared library
  it returns through `controlled_exit(1000 + code)` as `quit` does. Command completion
  and `oldhelp exit` come from the table entry.
- **`com_sweep.c`:** `sweep -analysis exit` is refused up front, as `-analysis quit`
  has been since [E-341](Enhancement-341.md): the analysis a sweep runs per point must
  leave the circuit standing. The script continues after the refusal.
- Nothing else consults the name. The `ic.file` scan in `inpcom.c` already ignores a
  control line that begins with a letter it does not examine, and the `cp_evloop("quit")`
  in `main.c` is the program's own call. With `set unixcom` an unknown command is handed
  to the shell; `exit` is found in the table first, so it ends ngspice rather than a
  child shell.

## Verification

| check | result |
|---|---|
| `exit` in a `.control` block, batch mode | no "no such command", the lines after it do not run, the done banner, status 0 |
| `exit 3` / `exit noask` | status 3 / status 0 |
| `exit 7` inside an `if`; `exit 2` inside a `repeat` | status 7; one pass, status 2 |
| `quit`, `quit 5` | unchanged (0, 5) |
| pipe mode: `exit`, `exit 4` | the session ends before the next line; status 0 / 4 |
| `oldhelp exit`, `oldhelp quit` | `exit : Quit ngspice (the same as quit).`; the `quit` line unchanged |
| `set askquit`, an unsaved plot: `exit` then `yes`; `exit noask` | the question, then the end; no question |
| `sweep … -analysis exit`, `-analysis quit` | both refused ("would destroy the circuit"), the script continues |

Full sweep 526 of 526 on both solvers.

## What this does not do

- `exit` is a command, not a shell exit: it ends ngspice (or, in the shared library,
  returns control to the host) exactly as `quit` does. It is not added to the
  documentation browser's subjects, which `quit` has none of either.
