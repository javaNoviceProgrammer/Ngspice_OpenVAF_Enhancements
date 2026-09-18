# Enhancement-663: a plain corner loop takes priority over `.option osdimc` — the automatic Monte Carlo is disabled for the loop, with a warning, and every corner runs at the nominal of the statistical parameters

**Scope:** F7 of the
[bug hunt of 2026-09-18](../docs/bug_hunts/2026-09-18_openvaf-r-corners-and-run-control.md),
decided by the user: corners take priority over `automc`. ngspice:
`src/osdi/osdisetup.c` (`OSDImcCornerPriority`, `OSDImcOptionSet`;
`osdimc_enabled` honours the priority; the interrupt reset clears it),
`src/include/ngspice/osdiitf.h`, `src/frontend/com_sweep.c` (`com_corners`:
standalone versus nested; `autocorner_run`: the pass, said once per circuit).
`examples/cornerscmd_examples/` (two checks added, 24 per solver),
`examples/autocorner_examples/` (one, 15). Handbook
[§3.7](../docs/handbook/03-ngspice-workflows.md). **ngspice only.**

**Suites:** [`cornerscmd_examples`](../examples/cornerscmd_examples/) 24 of 24
and [`autocorner_examples`](../examples/autocorner_examples/) 15 of 15 per
solver, both solvers (the new checks fail on the E-661 binaries); `vacorner`,
`savemc`, `mcyield` unchanged; full sweep 529 of 529 (`plotname`'s per-point
timing check tripped once under the parallel load and passes alone).

## What was wrong

Under `.option osdimc` (alias `automc`) every corner run of the `corners`
command and of `.option autocorner` was a fresh trial: the cornered parameters
pinned ([E-654](Enhancement-654.md)), the other statistical ones drawn again.
With `r` cornered (`std=5`), `q` and a per-instance `dm` uncornered:

| loop | tt row | ss row | ff row |
|---|---|---|---|
| `corners`, fresh deck | q 10, dm 0 | q 9.13, dm 0.53 | q 11.53, dm −0.07 |
| `corners` after one prior `op` | q 9.13, **r 85.98** | q 11.53, r 110 | q 8.74, r 90 |

The corner-to-corner difference of any output carried a fresh mismatch draw;
the `tt` row was the nominal only on a fresh deck and a random sample after any
prior run, the cornered parameter itself drawn there; and the table depended on
how many runs came before. `autocorner` behaved the same, and a `corners`
nested inside a `montecarlo` sample redrew per corner inside the sample.
`sweep` and `wcd` hold one trial across their loop ([E-535](Enhancement-535.md));
the corner loops did not, and nothing said so.

## What changed

A corner table is a PVT tool, and the user's rule is that corners win:

- **A standalone plain `corners` loop disables the option for the loop**, with
  a warning: *corners takes priority over .option osdimc (automc): the option is
  disabled for this loop and every corner runs at the nominal of the
  statistical parameters; `corners -mc N` draws them per corner*. Every corner
  runs at the nominal of the uncornered statistical parameters, the cornered
  ones at their corner. Afterwards the option is back and the trial sequence
  restarts at the baseline, as after `unset osdimc`.
- **`.option autocorner` disables it for the corner pass**, said once per
  circuit: a schematic host's corner plots are deterministic.
- **`corners -mc N`** is untouched: a montecarlo per corner draws by design.
- **Nested inside another loop command's sample** (`montecarlo N -analysis
  "corners …"`), the loop holds that one sample instead (the E-535 rule), so
  `q[tt] − q[ff]` is 0 within every sample and the outer command measures the
  corner table's distribution. No warning there.

The lever is `OSDImcCornerPriority(on)`, a depth `osdimc_enabled` tests beside
the option; `OSDImcOptionSet` says whether the option is set at all, for the
warning. A keyboard interrupt clears the depth with the other brackets.

## Verification

| check | result |
|---|---|
| `.option osdimc mcseed=3`; `op`; `corners -list tt ss ff -output q r`; `op`; `op` | the warning once; q 10 10 10, r 100 110 90; then q 10 (the baseline again) and 7.196 |
| `corners -list tt ss -mc 2 …` in the same deck | montecarlo per corner, no warning |
| `montecarlo 3 -analysis "corners -list tt ss ff -output q=…" -spec q[0]-q[2] -max 1e-9 -min -1e-9` | yield 100 % (3 of 3), no warning |
| `.option autocorner osdimc`, `save @qm[q] @qm[w]`, `op`, `op` | the warning once for two runs; the second pass's copies q 10 at tt and at ss, w 2 at ss |
| `.option osdimc` off | no warning, as before |
| the E-661 binaries on the same suites | the new checks fail |

Full sweep 529 of 529 on both solvers.

## What this does not do

- A single selected corner (`.option corner=ss`, `set corner=`) keeps the
  option: that is E-654's corner-plus-mismatch flow, which `montecarlo` under a
  corner and `corners -mc N` rely on. Only the loops take priority.
- The option is disabled for the loop, not removed from the deck: the next plain
  run draws again, from the baseline.
- `wcd` and `highsigma` walks inside a corner loop are not a case.
