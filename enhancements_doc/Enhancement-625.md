# Enhancement-625: a run stopped at a breakpoint is a row — `paused`, then the `resume`'s outcome

**Scope:** `src/frontend/mcsave.c` — `MCSAVErun()` takes `MCS_PAUSED` and writes the trial's
row at the pause, status `paused`, with its draws and its plot (so a `writemc` there lands
on it); `MCSAVEresumed()` sets that row `ok` or `failed` when the `resume` that continued
the same plot ends; `text_rewrite_last()` factored out of `MCSAVEappend()` for the
in-place rewrite. `src/frontend/spiceif.c` — `if_run()` emits the paused row at `E_PAUSE`
and reports the `resume` branch's outcome. `examples/writemc_examples/` grows 18 → 21
checks per solver; the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §8, the
suite README. **ngspice only.** F9 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`writemc_examples`](../examples/writemc_examples/) 21 of 21 per solver, both
solvers; `savemc_examples` 36 of 36; full sweep 505 of 505.

## What was wrong

```spice
.option osdimc savemc=f9.csv mcseed=3
v1 1 0 pulse(0 1 1u 1n 1n 10u 20u)
n1 1 0 rm
.model rm smcres r=1000
.control
pre_osdi smcres.osdi
op
stop when time > 2u
tran 1u 6u
writemc n=length(time)
delete all
resume                        ; runs to 6u: "No. of Data Rows : 77"
writemc n=length(time)
.endc
```
```
trial,analysis,status,@n1[dr],@rm[r],@rm[g],@rm[k],@rm[u]
1,op,ok,0,1000,0.001,2,50
```

The transient drew its trial at setup (`@rm[r]` = 966.08, `@n1[dr]` = 10.59), stopped at
the breakpoint, and was resumed to the end — and the file never had a row for it. The
recorder is called when a run-class command returns; a pause returns `E_PAUSE` before
that call, and `resume` is not a run-class command (it draws nothing), so neither end of
the trial wrote anything. Before Enhancement-624 the three `writemc` then landed on the
`op`'s row; since it they are refused ("the current plot tran1 was made after row 1 (op,
plot op1) by a run that has no row") — the misattribution gone, the trial still missing.

## What changed

- **The row is written at the pause, status `paused`.** The draws are in force and the
  plot exists; the row carries the draws as every row does, remembers its plot
  (Enhancement-624), and a `writemc` at the pause lands on it — the state of the run so
  far, `n=42`.
- **The `resume` that ends the run sets that row's outcome.** A resume that completes
  turns the paused row `ok`; one that fails (a `$fatal` past the breakpoint) turns it
  `failed`; one that pauses again — as a `stop when time > 2u` does at its first step,
  the condition holding — leaves it `paused`. The resume starts no row of its own: the
  row it updates is the most recent `paused` one, and only if the plot current at the
  end is that row's (a paused row whose plot is not the one continued is left alone). For
  csv/txt the last line is rewritten in place, an earlier line rewrites the file; the
  xlsx has the status at its next write.
- A `writemc` after the resume replaces the value on the same row (`n=77`), so a trial is
  one row wherever it stopped on the way.

```
trial,analysis,status,@n1[dr],@rm[r],@rm[g],@rm[k],@rm[u],n
1,op,ok,0,1000,0.001,2,50,
2,tran,ok,10.5877516433,966.081780302,0.00100964647744,2.03678297261,46.8426637886,77
```

A run left paused when the session ends stays `paused` in the file — the truth of it.

## Verification

| check | result |
|---|---|
| `op; stop when time > 2u; tran 1u 6u; writemc n=length(time)` and stop | row 2 `tran,paused` with its draws and `n=42` |
| … then `resume` (pauses again at once), `writemc`, `delete all`, `resume`, `writemc`, `op` | row 2 `ok` with `n=77` — one row for the trial, none for the resumes; the `op` is row 3 |
| … `resume` into a `$fatal` at 3 µs | row 2 `failed`; the `writemc` after it reads the run's own partial plot |
| `savemc=excel` through the same | the status is `ok`/`failed` in the workbook |
| the 18 existing checks (`[13]`'s no-row refusal now exercised by a run the recorder was off for); `savemc_examples` | unchanged, 36 / 36 |
| `writemc_examples` | 21 / 21, both solvers |
| full sweep | 505 of 505 |
