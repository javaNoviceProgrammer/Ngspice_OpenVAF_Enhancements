# Enhancement-618: the restore after `unset osdimc` keeps a loop command's push

**Scope:** `src/osdi/osdisetup.c` — `OSDImcNewRun()`'s option-off restore skips an entry
a bracketed loop command has pinned (its own push of this point), and still restores
over a pin left by a completed command; `src/frontend/mcsave.c` — `MCSAVErun()` reads the
OSDI columns on every row once the file has them, option on or off
(`cols_have_osdi()`). `examples/osdimc_examples/` grows 39 → 42 checks per solver; the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §7, the
suite README. **ngspice only.** F19 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`osdimc_examples`](../examples/osdimc_examples/) 42 of 42 per solver, both
solvers; the ten sibling `osdimc`/`savemc` suites green; full sweep 505 of 505.

## What was wrong

```spice
.param rr = 1000
.model rm rstat r={rr}
.control
op
op
unset osdimc
sweep rr 500 1500 500 -output r=@rm[r] -analysis op
print r                                   ; 1000  1000  1500   <- 500 expected first
.endc
```

The first run after `unset osdimc` puts every drawn parameter back to its nominal — the
documented restore. The sweep's first point had already pushed 500 through the machine
setter, and that run's restore wrote the nominal 1000 over it: the readback was 1000,
1000, 1500, with nothing said. An `op` between the `unset` and the sweep absorbed the
restore and the sweep was right — the wrong point depended on what ran before. The
`savemc` record of the same run was wrong in a second way: with the option off the
recorder no longer read the OSDI columns, so every row after the `unset` repeated the
last trial's draws (`@rm[r]` = 987.78, `@n1[dr]` = −10.999) while the devices held
1000 / 500 / 1000 / 1500 and 0.

## What changed

- **The restore keeps what a bracketed command has just pushed.** A machine write pins
  the parameter's nominal entry (Enhancement-535); under an open hold — a `sweep`,
  `optimize`, `wcd`, `loadpull` bracket — a pinned entry is that command's own write of
  this point, and the command restores what it pushed when it ends, so the option-off
  restore leaves it alone. Outside a hold a pin is a leftover of a command that has
  completed — a `.dc @rm[r]` sweep restores the *drawn* value it found — and the
  restore proceeds as before. Entries the command did not touch (`@n1[dr]`) are restored
  at the same run, as before.
- **The `savemc` rows read the devices, option on or off**, once the file carries OSDI
  columns: after `unset osdimc` a row shows the value in force — the restored nominal,
  the sweep's point — instead of the last draw. A deck whose recorder starts with the
  option off still records no OSDI columns and still says so once, as E-610 has it.

```
print r                                   ; 500  1000  1500
```
```
trial,analysis,status,@n1[dr],@rm[r]
1,op,ok,0,1000
2,op,ok,-10.999234629,987.784797889
3,op,ok,0,500
4,op,ok,0,1000
5,op,ok,0,1500
```

`montecarlo` right after the `unset` was already right for the netlist's own draws —
since Enhancement-616 a fast-path re-draw *is* the entry's nominal, so restoring it is a
no-op — and stays so; the check is there to keep it.

## Verification

| check | result |
|---|---|
| `op; op; unset osdimc; sweep rr 500 1500 500` | the sweep reads 500, 1000, 1500; `dr` restored to 0 at the first point; the `savemc` rows carry those values |
| `op; op; dc @mm[r] 900 1100 100; unset osdimc; op` | the `.dc`'s leftover pins do not block the restore: 1000 and 0 |
| `unset osdimc` then `montecarlo 3` on a netlist-drawn model slot | each sample runs at its own draw (`@mm[r]` = `mm:r`), `dr` at 0 |
| the 39 existing checks; `paramgiven`, `mcpolicy`, `osdidist`, `wcd`, `huntfix`, `dcxsweep`, `constguard`, `autoopts`, `savemc`, `writemc` | unchanged |
| `osdimc_examples` | 42 / 42, both solvers |
| full sweep | 505 of 505 |
