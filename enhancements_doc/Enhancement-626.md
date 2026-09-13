# Enhancement-626: a `dc` that sweeps a recorded parameter leaves its cell empty, said once

**Scope:** `src/frontend/mcsave.c` — a per-row list of the parameters the `dc` swept, fed
from two sides: the OSDI snapshot's per-run write count (`OSDImcSnapshotItem.writes`, with
the span of the levels) and the `dc` job's own resolved names (`TRCVvName`: a source or
resistor, the literal `@owner[param]` of an instance or model parameter, E-534's target
list while it is still there); those columns are empty on the row and one note names them
with their levels. `src/osdi/osdisetup.c` / `osdiparam.c` / `osdidefs.h` — the machine-write
hook takes the stored value and counts the run's writes per entry (`run_writes`, zeroed at
`OSDImcNewRun`, spanned but for the last, which is the sweep's restore);
`include/ngspice/osdiitf.h` — the snapshot callback takes an `OSDImcSnapshotItem`.
`examples/savemc_examples/` grows 36 → 37 checks per solver; the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §8, the
suite README. **ngspice only.** F10 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`savemc_examples`](../examples/savemc_examples/) 37 of 37 per solver, both
solvers; `writemc`, `osdimc`, `mcpolicy`, `dcxsweep` green; full sweep 505 of 505.

## What was wrong

```spice
.option osdimc savemc=f10.csv mcseed=3
v1 1 0 1
n1 1 0 rm
.model rm smcres r=1000            ; (* std=25 *) r
.control
pre_osdi smcres.osdi
op
dc @rm[r] 900 1100 100             ; -1/i(v1) = 910.6, 1010.6, 1110.6 (r + dr, dr = 10.59)
print @rm[r]                       ; 966.08 -- put back by the sweep
sweep @rm[r] 900 1100 100 -analysis op
.endc
```
```
trial,analysis,status,@n1[dr],@rm[r]
1,op,ok,0,1000
2,dc,ok,10.5877516433,966.081780302     <- the device never ran at 966.08
3,dc,ok,-1.33124016944,991.85272636     <- the sweep command became one dc run: same
```

The `dc` drew its trial at the run's start (966.08), then swept `r` through the machine
setter — 900, 1000, 1100, each pinning the entry past the draw (Enhancement-535) — and
ended by putting back the value it had found. The row is made after the run and reads the
devices: 966.08, a draw the device never ran at. Enhancement-610's promise for a pinned
draw was "what the device actually ran with", and for a run that swept the parameter no
one number is that. The netlist side had the same face: `dc r1 900 1100 100` over a
resistor whose value is a draw recorded the draw the expansion wrote into the slot
(`r1 = 1023.1`), and `dc @m1[w] 2u 4u 1u` the drawn `m1:w`, while the devices ran the
levels.

## What changed

- **A parameter the `dc` swept has no value on that row.** Its cell is empty, and the row
  says so once:
  ```
  Note: savemc: row 2 (dc) sweeps @rm[r] (3 levels, 900 to 1100): the device ran at each level, not at a draw, so that cell is left empty on the row (said once)
  ```
  The other columns keep their values — `@n1[dr]` = 10.59 on that row is what the
  device ran with at every level.
- **Which parameters, from two sides.** The OSDI entries report how many machine writes
  they took *during* the run (a count zeroed when the run begins, so a `sweep` command's
  push before each point's run is not one) with the span of the levels — so a wildcard
  family or a nested inner sweep is caught by what was actually written; the netlist
  slots come from the `dc` job's resolved names: a source or resistor by its name (`r1`),
  an instance or model parameter from the literal `@owner[param]` as `owner:param`
  (`m1:w`, `rm:r`), E-534's target list while the sweep has not yet freed it. The level
  count in the note is the job's where the name matches (a nested outer parameter is
  written once per inner pass); otherwise only the span is given.
- **Only a `dc` row is read this way** — a `dc` command, or a `run` whose job is a `.dc`
  card. Other analyses' machine writes leave the device at the draw when they end (a
  `sens` perturbation is restored before the run is over), and the draw is then the value
  in force. A `sweep … -analysis tran` that runs one analysis per point is one row per
  point with the pushed level, as before (900, 1000, 1100).

```
trial,analysis,status,@n1[dr],@rm[r]
1,op,ok,0,1000
2,dc,ok,10.5877516433,
3,dc,ok,-1.33124016944,
4,op,ok,-11.3705654083,1006.67766369
```

## Verification

| check | result |
|---|---|
| `dc @sm[r] 900 1100 100` | `@sm[r]` empty on its row, `r1`, `m1:w`, `@n1[dr]` kept; the note once, "3 levels, 900 to 1100" |
| `dc r1 900 1100 100`, `dc @m1[w] 2u 4u 1u` | `r1` empty on the one row, `m1:w` on the other, everything else kept |
| `dc v1 0 1 0.5` | every value kept |
| `dc @sm[r] 900 1100 100 @n1[dr] -10 10 10` | both empty on the row |
| `run` with a `.dc @sm[r]` card | `@sm[r]` empty on the `run` row |
| `sweep @sm[r] 900 1100 100 -analysis "tran 1u 3u"` | three rows with 900, 1000, 1100 |
| the 36 existing checks; `writemc`, `osdimc`, `mcpolicy`, `dcxsweep` | unchanged |
| `savemc_examples` | 37 / 37, both solvers |
| full sweep | 505 of 505 |
