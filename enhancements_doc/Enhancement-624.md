# Enhancement-624: `writemc` lands only on the row of the run whose plot it reads

**Scope:** `src/frontend/mcsave.c` — every row remembers the plot its run made
(`MCSAVErunBegin()` notes the plot current before the run; a run that failed before it
made one records none); `MCSAVEplotIsRow()` decides whether a value read off the
current plot may go onto the last row; `com_writemc` asks it first. `src/frontend/spiceif.c`
— `if_run()` calls `MCSAVErunBegin()` before `doAnalyses`. `examples/writemc_examples/`
grows 15 → 18 checks per solver; the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §8.1, the
suite README. **ngspice only.** F8 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md); the
misattribution half of F9 falls with it (a paused run's plot is refused; that run still
has no row).

**Suites:** [`writemc_examples`](../examples/writemc_examples/) 18 of 18 per solver, both
solvers; `savemc_examples` 36 of 36; full sweep 505 of 505.

## What was wrong

```spice
.option osdimc savemc=f8.csv mcseed=3
v1 1 0 1
n1 1 0 rm
.model rm smcres r=30           ; (* std=25 *) r from (0:inf) -- some draws fall below 0
.control
pre_osdi smcres.osdi
repeat 12
  op
  writemc ia=i(v1)
end
.endc
```
```
1,op,ok,0,30,...,-0.0333333333333
2,op,failed,10.5877516433,-3.91821969775,...,-0.0333333333333      <- row 1's value
3,op,ok,-1.33124016944,21.8527263605,...,-0.0487294141706
4,op,ok,-11.3705654083,70.595883393,...,-0.0168846708473
5,op,failed,-15.4422367773,-4.35511767187,...,-0.0168846708473     <- row 4's value
```

Trials 2 and 5 drew `r` below the model's range; the `op` was refused at setup
("Parameter r of 'rm' is out of bounds"), made no plot, and the row was written as
`failed` — correctly, the draw happened. But the previous successful run's plot stayed
current, and `writemc ia=i(v1)` read it: the failed row carried the *previous* trial's
current, presented as its own. `montecarlo -writemc` never had this — a sample whose
analysis failed is skipped before its `-writemc` items (Enhancement-438) — but the plain
command did no such check. The same misreading was behind half of F9: after `stop when
time > 2u; tran 1u 6u` the paused run has no row, and every `writemc` after it landed
on the row of the `op` before it.

## What changed

- **Every row remembers the plot its run made.** `if_run()` notes which plot is current
  before `doAnalyses`; when the row is written a run that completed has made the current
  plot, and a run that failed has made one only if the current plot changed under it — a
  transient that dies part-way (a Verilog-A `$fatal`, a timestep too small) keeps its
  partial plot; an operating point refused at setup leaves the previous run's. The
  pointer is kept for identity only; the plot's name goes with it for the messages.
- **`writemc` checks the row against the plot it reads.** The value goes on when the
  current plot is the row's own, or an older one — a `setplot` back to an earlier run is
  deliberate. It is refused, once per command, when the row's run failed before it made a
  plot ("row 2 (op) failed before it made a plot, so the current plot op1 is another
  run's; nothing is put on that row") and when the current plot was made *after* the row
  ("the current plot tran1 was made after row 1 (op, plot op1) by a run that has no row")
  — the paused-run case of F9. The cell stays empty, which is what the `failed` status
  and an empty cell already meant on `montecarlo`'s rows.
- A failed run that made its own plot still records from it: a transient that `$fatal`s
  at 3 µs writes `n=48`, `tlast=2.94 µs` onto its `failed` row — that run's data.

```
1,op,ok,0,30,...,-0.0333333333333
2,op,failed,10.5877516433,-3.91821969775,...,
3,op,ok,-1.33124016944,21.8527263605,...,-0.0487294141706
4,op,ok,-11.3705654083,70.595883393,...,-0.0168846708473
5,op,failed,-15.4422367773,-4.35511767187,...,
```
```
writemc: row 2 (op) failed before it made a plot, so the current plot op1 is another run's; nothing is put on that row
writemc: row 5 (op) failed before it made a plot, so the current plot op3 is another run's; nothing is put on that row
```

`montecarlo -writemc` is untouched: it skips a failed sample before its items, and its
own sample plot is the one it reads.

## Verification

| check | result |
|---|---|
| `repeat 12 / op / writemc ia=i(v1)` with draws that fall outside the range | the failed rows' cells empty, the ok rows filled, one message per failed row naming the row and the plot really current |
| a transient killed by `$fatal` at 3 µs, then `writemc n=length(time) tlast=…` | a `failed` row that records from its own partial plot, no message |
| `op; stop when time > 2u; tran; writemc; resume; writemc` | both refused, naming `tran1` as made after row 1 by a run that has no row |
| `op; setplot op1; writemc first=i(v1)` | writes onto the later `op`'s row (an older plot, chosen) |
| the 15 existing checks; `savemc_examples` | unchanged, 36 / 36 |
| `writemc_examples` | 18 / 18, both solvers |
| full sweep | 505 of 505 |
