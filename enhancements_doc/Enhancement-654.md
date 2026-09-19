# Enhancement-654: process corners declared on Verilog-A parameters — `(* corner="ss=115, ff=-10%, sf=+3sigma" *)` and `.option corner=<name>`

**Scope:** Compiler: `openvaf/sim_back/src/module_info.rs` (the `corner`
attribute parsed into `ParamCorner` entries; `parse_corner_list`,
`parse_corner_value`; six diagnostics), `openvaf/sim_back/src/lib.rs`
(re-exports), `openvaf/osdi/src/metadata.rs` (`corner_params`),
`openvaf/osdi/src/lib.rs` (the `OSDI_CORNER_{COUNTS,INFOS,NAMES}` side table;
the names interned). ngspice: `src/osdi/osdi.h` (`OsdiCornerInfo`,
`OsdiCornerParam`), `src/include/ngspice/osdiitf.h` (the registry fields,
`OSDImcCornerSelected`), `src/osdi/osdiregistry.c` (the records built at load),
`src/osdi/osdisetup.c` (the corner read, check, capture, apply and restore; the
draw appliers skip a cornered parameter; the snapshot), `src/frontend/spiceif.c`
(`corner` a known option), `src/frontend/mcsave.c` (a cornered run is recorded).
`examples/vacorner_examples/` (new, 18 checks per solver); handbook
[§2.13](../docs/handbook/02-verilog-a-language.md) row and
[§3.7](../docs/handbook/03-ngspice-workflows.md). Requested by the user: phase 1
of the corner design (a `corners` loop command and `.option autocorner` are
phases 2 and 3).

**Suites:** [`vacorner_examples`](../examples/vacorner_examples/) 18 of 18 per
solver, both solvers (16 fail on the E-653 binaries); `osdimc`, `savemc`, `wcd`,
`highsigma`, `mcfastpath`, `mcrecord`, `lhs` unchanged; the compiler's workspace
tests green; full sweep 527 of 527.

## What was asked

The statistics attributes ([E-53x](Enhancement-535.md) and on) let a Verilog-A
model carry its own Monte Carlo: `(* std=0.02 *)` on a parameter, `.option osdimc`
in the deck. A process corner is the deterministic counterpart — every process
parameter at a named position at once, `ss`, `ff`, `sf`, `fs` — and most foundry
corners are defined as a signed multiple of the same global sigma. There was no
way to say that in the model, and no way to select it from a deck short of a
`.lib` section with a second model card per corner.

## What changed

**The attribute.** One string attribute on a parameter, entries `name=value`
separated by commas and/or whitespace (a trailing comma is tolerated):

```verilog
(* corner="ss=115, ff=88" *)                     parameter real rsh = 100;
(* corner="ss=+10% ff=-10%" *)                  parameter real k   = 2.0;
(* std=0.02, corner="ss=+3sigma, ff=-3sigma" *)  parameter real vth = 0.45;
(* std_rel=0.1, dist="lognormal", trunc=2, corner="ss=+3sigma" *) parameter real tox = 2n;
```

| value | meaning |
|---|---|
| `115`, `2.2n`, `1.5k` | the parameter's value at the corner (a real literal, LRM scale factors) |
| `+10%`, `-10%` | a fraction of the nominal, `nominal · (1 + f)` |
| `+3sigma`, `-2sigma` | a multiple of the declared `std`/`std_rel`, through the transform a draw uses: a lognormal's log domain, a truncation's clamp (`trunc=2` holds `+3sigma` at 2), a uniform's half-width; it needs the statistics, so `sigma` without them is an error |

Names fold to lower case, as ngspice folds a deck; `SS` and `ss` in one attribute
are the same corner, and an error. The spelling inside a string is literal:
`ss=2*tox0` is refused, the way extracted corners are numbers anyway. The
diagnostics, in the E-634 style: a value that is not a string (error), a
malformed entry naming the entry and the reason (error), a name twice (error),
`sigma` without statistics (error), a percentage of a default of 0 (warning), the
attribute given twice (warning, the last wins), on an integer or string
parameter, a localparam, or a variable (warning, nothing exported).

**The export.** A new optional side table beside the statistics tables:
`OSDI_CORNER_COUNTS` (entries per descriptor), `OSDI_CORNER_INFOS` (one 16-byte
record per (parameter, corner): id, kind, value) and `OSDI_CORNER_NAMES` (the
corner's name for each record). An object without corners carries no symbol, an
older simulator sees none; no descriptor-ABI change.

**The deck.** `.option corner=ss` — or `set corner=ss` between runs — selects the
corner. On every run-class command ngspice writes each cornered parameter's value
through the ordinary setter, on the first run too: the nominals are resolvable
only after one setup pass, so the corner rides the pending path the draws use and
`OSDIsetup` applies it right after its setup loops, before `OSDItemp` evaluates
the init-resident code. The rules:

- A cornered parameter does not draw under `.option osdimc`: the corner pins the
  process coordinate, mismatch on the other parameters goes on. A `wcd` or
  `highsigma` walk coordinate on it is consumed and ignored, so the walk's
  dimensions do not shift (since [E-667](Enhancement-667.md) it is no
  dimension at all: the count is of the free axes and the held ones are named).
- A parameter that names other corners but not this one sits at its nominal. A
  model type that declares corners but none of this name runs at nominal, said
  once per (type, name). A name no loaded Verilog-A model declares fails the run:
  `Error: .option corner=sss: no loaded Verilog-A model declares a corner of that
  name (declared: ss, ff); the run is refused` — a typo must not run the nominal
  under a corner's name. A deck with no Verilog-A device is left alone.
- `tt`, `nom` and `nominal` are the nominal. `set corner=tt` selects it from a
  script; `unset corner` returns to the deck's `.option`, or to the nominal
  without one, and the parameters are put back on the next run.
- `alter`/`altermod` of a cornered parameter recentres it (the E-531 rule): a
  percentage or sigma corner then moves with the new nominal, an absolute one
  writes its value over it at the next run.
- `showmod`/`show` print the cornered value; `.option savemc` records the
  cornered parameters under a corner as it records the draws under `osdimc`, a
  corner-only parameter included; `osdimc_verbose` says each write:
  `corner ss: rm:k = 2.2 (nominal 2, +10%)`.

## Verification

| check | result |
|---|---|
| `.option corner=ss`, first run | 115; 2.2; 0.51; `2n·e^0.2` (clamped at 2 sigma); 1.2k on both instances |
| `ff` | 88; 1.8; 0.39; the parameters without an `ff` entry at nominal |
| no option; `tt`; `nom` | nominal |
| comma, whitespace, mixed separators | one table |
| `2.2n`, `1.5k`, `1M`, `1m` | 2.2e-9, 1500, 1e6, 1e-3 |
| `+1sigma` on a uniform | one half-width |
| `set corner=` between runs; `tt`; `unset` without and with a deck option | 88, 100, 88, 100; 88 then 115 |
| `.option osdimc` beside the corner | the cornered statistical parameter 110 on three trials, the other one draws |
| `altermod` | `k=3` then 3.3; `rsh=200` then 115 |
| `showmod` | the cornered values |
| `.option savemc` | the cornered parameters in the row, a corner-only one too |
| `.option corner=sss` | the error naming `ss, ff`; the run refused |
| a type lacking the corner | the note once; its parameters nominal, the other type cornered |
| a deck with no Verilog-A device | runs |
| `SS`; `set corner=FF` | `ss`; `ff` |
| the compile-time diagnostics | five errors, five warnings, each worded |
| `osdimc_verbose` | `corner ss: rm:rsh = 115 (nominal 100, absolute)`, `+10%`, `+3 sigma` |
| `montecarlo 4 -analysis op` under `ss` | every sample row 110, the uncornered one varies |

Full sweep 527 of 527 on both solvers.

## What this does not do

- No `corners` loop command and no `.option autocorner` yet: one corner per run,
  selected by the option. Those are the next phases.
- No corner-name column in the `savemc` file; the values themselves say.
- A literal corner value outside the parameter's declared range is not judged at
  compile time; the run fails with the device's own located range error, as a
  draw does.
- A corner on a parameter whose default is derived from another parameter
  ([E-633](Enhancement-633.md)) is formed on the nominal captured at the first setup.
- `.lib` corner sections are untouched: they remain the way to switch whole model
  cards, and the two compose.
