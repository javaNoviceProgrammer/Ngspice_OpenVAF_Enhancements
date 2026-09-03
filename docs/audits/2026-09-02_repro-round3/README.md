# Reproduction decks — LRM audit round 3 (2026-09-02)

Every finding in [`../2026-09-02_LRM-audit-round3.html`](../2026-09-02_LRM-audit-round3.html)
was reproduced with the files here, against the **committed** binaries in
`bin/macos/apple-silicon/` (and re-checked against the locally built
`OpenVAF-master-20260610/target/opt/openvaf-r` + `ngspice-46/build/src/ngspice`
— identical results on both).

## Running one

```
openvaf-r <name>.va -o <name>.osdi
ngspice -b <name>.cir
```

`exh.cir` and `exh2.cir` write into `ex/` and `ex2/`; create those first
(`mkdir -p ex ex2`). `modes.cir` reads `data.txt`; `mch.cir` and `mch2.cir` read and
rewrite `mode1.txt`/`mode2.txt`/`mode3.txt`. All four data files are included, so
restore them from git before a re-run.

## After the fix

These decks record the findings **as measured**, so several of them no longer
compile or no longer misbehave now that [Enhancement-541](../../../enhancements_doc/Enhancement-541.md)
has landed — which is the point. `mfva.va`, `rng1.va` and `al.va` are refused
by the compiler outright (the illegal `#(.$mfactor(-3))`, the out-of-range
flips, and LRM 9.20's two error rules), and the rest now produce the LRM's
answer instead of the one recorded here. To reproduce the findings themselves,
run them against the binaries the audit measured — the tree at commit
`cb8a6528`.

## Which deck shows which finding

| deck | finding |
|---|---|
| `cbig.va` / `cbig.cir` | **F1** — every display and file write from an `analog initial` block is dropped; `$debug`/`$info` survive, which proves the block ran |
| `ini.va`, `fw.va` | **F1** — the same statements in `@(initial_step)` vs `analog initial`, side by side |
| `dio.va` / `dio.cir` | **F2** — one diode `.op`: `$strobe` prints 1 line, `$warning` prints 21 (the whole Newton walk) |
| `pair.va` / `pair.cir` | **F2** — `$strobe`/`$warning`/`$info`/`$error` in one block over a 5-point sweep: 5 vs 12 lines |
| `sev.va` + `si3.cir` | **F3** — `$error` in `analog initial` does not stop the run |
| `fat.va` + `fatbody.cir` | **F3** control — `$fatal` does stop it |
| `sev2.va` / `sev2.cir` | **F3** — no time or swept-variable value in any severity message |
| `exh.va`, `exh2.va` | **F4** — the 31st multichannel descriptor is `0x8000_0000`; writes to it vanish |
| `mch2.va` / `mch2.cir` | **F5** — read, close, reopen `"w"`: the mode change is ignored and the write is lost, with an append control in the same block |
| `mch.va` / `mch.cir` | **F5** — the same in the read to append direction |
| `mfva.va` / `mfva.cir` | **F6** — `#(.$mfactor(-3))` sign-inverts a passive device, silently |
| `ang.va` / `ang.cir` | **F7** — `$angle` 200+200 gives 400, no modulo 360 |
| `rng1.va`, `hsp.va` | **F7** — Table 9-29 allowed values unenforced on both routes |
| `al.va` | **F8** — LRM 9.20's two mandated errors are missing (compiles clean) |
| `wr.va` / `wr.cir` | **F9** — each `$write` carries its own instance prefix |
| `reuse.va` | note — a closed channel is not reused within an evaluation (a consequence of the 9.5.9 deferred close, not a finding) |

## Decks that measured conformance (kept for the record)

| deck | what it confirms |
|---|---|
| `ai_acc.va`, `ai_op.va`, `ai_contrib.va`, `ai_evt.va` | LRM 5.2.1's four `analog initial` restrictions, each with a precise diagnostic |
| `air.va` / `air.cir` | LRM 5.2.1 re-execution — `analog initial` re-runs when a swept parameter it reads changes |
| `modes.va` / `modes.cir` | all 15 Table 9-24 open modes; failure and a bogus mode both return 0 |
| `sp.va`, `spn.va` | Table 9-27 `$simparam` names; an unknown name with no default is a warning plus a runtime fatal |
| `fmt.va` / `fmt.cir` | Table 9-22/9-23 format specifiers in both cases (`%h` and `%H`, …) |
| `tie.va` + `tie.dat` | LRM 9.21.4's closest-point tie rule — equidistant snaps away from zero |
| `dfio.va` / `dfio.cir` | LRM 9.5.9 holds for file writes: one line at the converged point, not 21 |
