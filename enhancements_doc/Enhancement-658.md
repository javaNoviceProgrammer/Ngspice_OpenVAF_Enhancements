# Enhancement-658: the first cornered run after a nominal run under `.option osdimc` corners every declared parameter — cornered parameters captured at every setup

**Scope:** F1 of the
[bug hunt of 2026-09-18](../docs/bug_hunts/2026-09-18_openvaf-r-corners-and-run-control.md).
ngspice: `src/osdi/osdisetup.c` (`osdimc_capture`: the cornered parameters are
captured at every setup, corner on or off). `examples/vacorner_examples/`
(three checks added, 26 per solver). **ngspice only**; the compiler and the
OSDI tables are untouched.

**Suites:** [`vacorner_examples`](../examples/vacorner_examples/) 26 of 26 per
solver, both solvers (the three new checks fail on the E-656 binaries, the last
ones built; E-657 did not touch this path); `cornerscmd`, `autocorner`, `osdimc`,
`savemc`, `sweepanalysis`, `paramgiven` unchanged; full sweep 529 of 529.

## What was wrong

```
.option osdimc
.control
op                       * the nominal baseline
set corner=ss
op
print @rm[rsh] @rm[k] @rm[vth] @n1[ri]   * 100, 2, 0.51, 1000 -- should be 115, 2.2, 0.51, 1200
op
print @rm[rsh] @rm[k] @rm[vth] @n1[ri]   * 115, 2.2, 0.51, 1200
.endc
```

With the E-654 model (`rsh` an absolute corner, `k` a percentage, `ri` an
instance absolute, `vth` a sigma corner on `std=0.02`), a nominal run under
`.option osdimc` followed by `set corner=ss` gave, on the first cornered run,
`vth` at its corner and `rsh`, `k`, `ri` at nominal; the second run at the same
corner had all four. Without `osdimc` the first run was right. The same through
the loop commands: `corners -output` under `osdimc` printed its `ss` row nominal
and its `ff` row right (by `ff` the capture had happened); `.option autocorner`
recorded its first `ss` pass with 1000/100/2; a `sweep` as the first cornered
run had its first point at nominal and the rest at the corner.

The cause was an asymmetry in the nominal table. `osdimc_capture`, which runs at
every setup, captured the statistical parameters whenever `osdimc` was on and the
cornered parameters only while a corner was on. After a nominal run under
`osdimc` the table was therefore populated (the statistical parameters) and not
stale, so `OSDImcNewRun` took its direct path — the draws, then the corner —
instead of flagging the run pending for the setup; the corner writer found no
entry for a corner-only parameter and returned in silence. The next setup
captured them (the corner was on by then) and the next run applied them.
`montecarlo` and an `altermod` before the corner were not affected: their table
reset or stale mark takes the pending path, on which the setup captures first.

## What changed

`osdimc_capture` captures the cornered parameters whenever the model declares
corners, corner on or off — as it captures the statistical ones under `osdimc`.
A cornered parameter's nominal is then in the table from the first setup on, and
a corner selected after any number of nominal runs is applied in full on its
first run, on the direct path as on the pending one. Nothing else moves:

- A second capture of a parameter already in the table is a no-op
  (`osdimc_find`), so the entry keeps the nominal of the first setup, never a
  cornered value (the capture precedes the corner's writes on the pending path,
  and on the direct path the corner is written before the setup).
- `.option savemc` and the `osdimc` snapshot enumerate from the compiler's
  tables, not from the nominal table, so what a run records is unchanged.
- `alter`/`altermod` of a cornered parameter recentres its entry with the corner
  off too — the same nominal a later capture would have read from the device —
  and E-614's stale marking now covers a cornered parameter whose default may
  read a sibling the user wrote: its default is re-resolved at the next setup.
- The restore when the corner goes off, the draw appliers' skip of a cornered
  parameter and the `wcd`/`highsigma` walk are as before.

## Verification

| check | result |
|---|---|
| `.option osdimc`; `op`; `set corner=ss`; `op`; `op` | 115, 2.2, 0.51, 1200 on the first cornered run and on the second |
| `corners -list tt ss ff -output …` under `osdimc` | tt 100/2/1000, ss 115/2.2/1200, ff 88/1.8/1000 |
| `op`; `set corner=ss`; `sweep v1 1 2 1 -analysis op` under `osdimc` | both points 115 and 2.2 |
| `.option osdimc autocorner`, `save @rm[rsh] @rm[k] @n1[ri]`, `op` (by hand) | the `autocorner1` plot's `_ss` copies 115, 2.2, 1200; `_ff` 88 |
| the E-656 binaries on the same suite | the three new checks fail (100, 2, 1000 on the first run) |

Full sweep 529 of 529 on both solvers.

## What this does not do

- The corner loops under `osdimc` still let every corner be a fresh trial, so the
  uncornered statistical parameters redraw between corners (hunt F7). That is a
  design question — whether a corner loop should hold one mismatch sample —
  not this fix.
- A `sweep` that changes the corner between its points is not a case: the
  `corner` variable is read once per run.
