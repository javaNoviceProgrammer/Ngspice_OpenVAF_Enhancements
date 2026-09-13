# Enhancement-633: a drawn parameter whose default depends on another drawn parameter follows it — `(* std *) r3 = 2*r` draws around 2·r(drawn)

**Scope:** compiler — `openvaf/osdi/src/metadata.rs` (`stat_params()` reports whether each
statistical parameter's default is a compile-time constant), `openvaf/osdi/src/lib.rs`
(the optional `OSDI_STAT_PARAM_DERIVED` side-table, one `uint32` per statistics entry,
exported only when some entry is derived — the E-554 pattern). Simulator —
`src/osdi/osdi.h` (`OsdiStatParam.derived`), `osdiregistry.c` (reads the table; absent →
0), `osdisetup.c`: `osdimc_apply_type` leaves a derived parameter the deck never gave to
the setup's tail, where `osdimc_apply_derived` clears its given flag, runs the model's
setup once more so the default re-resolves from the trial's other draws, takes that value
as the trial's nominal and puts the draw on top; the option-off restore leaves such a
parameter stale for the setup to re-derive. `examples/osdimc_examples/` grows 44 → 49
checks per solver (`smcderiv.va` new). **Both sides.** F21 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`osdimc_examples`](../examples/osdimc_examples/) 49 of 49 per solver, both
solvers; `paramgiven`, `osdidist`, `mcpolicy`, `huntfix`, `savemc` green; full sweep 506
of 506 (every model recompiled by the new compiler).

## What was wrong

```verilog
(* std=10.0 *) parameter real r  = 1000.0 from (0:inf);
               parameter real r2 = 2*r;
(* std=10.0 *) parameter real r3 = 2*r;
```
```
osdimc: trial 2: mm:r = 981.813 (nominal 1000)
osdimc: trial 2: mm:r3 = 2004.9 (nominal 2000)
@mm[r]  = 9.818129e+02
@mm[r2] = 1.963626e+03          <- 2 x 981.81: re-derived by the setup
@mm[r3] = 2.004895e+03          <- 2000 + 4.9: a nominal captured once
```

The plain `r2` followed the drawn `r` at every trial — the model's setup re-resolves a
never-given parameter's default from the current values. `r3` did not: its nominal was
captured at the first setup (2000) and every trial wrote `2000 + δ`; a written parameter
counts as given, so the setup never recomputed its `2*r`. A model author writing
`(* std *) parameter real r3 = 2*r` means 2·r(drawn) + δ, and the dependency was lost
for exactly the parameter that carried statistics.

## What changed

- **The compiler says which defaults are derived.** `param_defaults()` already knows
  whether a default is a compile-time constant; `stat_params()` now carries that per
  statistics entry, and the object exports `OSDI_STAT_PARAM_DERIVED` when any is — an
  older object is read as all-constant, an older simulator ignores the symbol.
- **A derived parameter the deck never gave is drawn after its default is
  re-resolved.** The pre-setup apply skips it (its walk coordinate consumed, so a walk
  lands the same coordinate on the same parameter); the setup runs with the trial's
  other draws in place; in the setup's tail `osdimc_apply_derived` clears the
  parameter's given flag, runs the model's `setup_model` (and `setup_instance` for an
  instance-level one, the collapse decision kept) once more so the default re-resolves
  from those values — `2·r_drawn` — takes that as the trial's nominal and writes
  `nominal + δ`. OSDItemp then runs the setups again with every value final, so a hoisted
  `geff = 1/(r + r3)` sees the drawn `r3`. The reset path (montecarlo's per-sample
  re-source) goes through the same tail, so both paths agree.
- **A parameter the deck gave keeps its given nominal** (`.model mg deriv r3=2500` draws
  around 2500), a `$param_given`-gated one is still left alone (E-555), and **the
  option-off restore** leaves a derived never-given parameter stale for the setup to
  re-derive from the restored values — `unset osdimc` puts `r3` back to 2·1000, not to
  the last trial's 2·r.

```
osdimc: trial 2: mm:r = 981.813 (nominal 1000)
osdimc: trial 2: mm:r3 = 1968.52 (nominal 1963.63)        <- 2 x 981.81, then + 4.9
```

## Verification

| check | result |
|---|---|
| `r2 = 2*r`, `(* std *) r3 = 2*r`, `(* type="instance", std *) dr = 0.01*r` over three `op` | `r2 = 2r`; `r3 = 2·r_drawn + δ`; `dr = 0.01·r_drawn + δ`; `mg` with `r3=2500` given draws around 2500 |
| a hoisted `geff = 1/(r + r3)` against the read-back parameters | equal to every digit, plain and montecarlo paths |
| `montecarlo 3` (the reset path) | every sample's `r3` around its own `2·r`, `dr` likewise, the given `r3` around 2500 |
| `unset osdimc` | `r` = 1000, `r3` = 2000 (re-derived), `dr` = 10, the given `r3` = 2500 |
| the object | exports `OSDI_STAT_PARAM_DERIVED` (`[0, 1, 1]` for r, r3, dr) |
| the 44 existing checks (E-614's `rb = rl` dependency among them); `paramgiven`, `osdidist`, `mcpolicy`, `huntfix`, `savemc` | unchanged |
| `osdimc_examples` | 49 / 49, both solvers |
| full sweep | 506 of 506 |
