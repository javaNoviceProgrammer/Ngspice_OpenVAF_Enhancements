# Enhancement-724: the adapter `autoadapt` injects takes a name the deck does not use, and a batch `.meas` under `.option autocorner` names its corner before each run's results — a user's own `n_adapt1_` made the injection "device already exists, bail out" on the user's line, and three corners' measures printed in turn with nothing to tell them apart

**Scope:** F8 of the
[five-options dig of 2026-09-25](../docs/bug_hunts/2026-09-25_five-options-dig.md).
**ngspice only.** `src/spicelib/parser/inp2n.c` (`adapt_name_taken`, the naming loop
in `INPadapt`), `src/frontend/measure.c` (`do_measure`, the corner header).
[`examples/autoadapt_examples/`](../examples/autoadapt_examples/) (1 check, 27 per solver);
[`examples/autocorner_examples/`](../examples/autocorner_examples/) (section [16], 2
checks, 23 per solver). The hunt page.

**Suites:** `autoadapt` 27 of 27 per solver, both solvers (26 of 27 on the E-722
binaries); `autocorner` 23 of 23 (22 of 23); `autoopts` 43 of 43, `adaptmsg`,
`adaptlisted`, `adaptquiet`, `busmix`, `busmixed`, `subbus`, `vacorner`, `cornerscmd`,
`savecorner`, `osdimc`, `savemc` unchanged; no new build warnings; full sweep, run alone.

## What was wrong

**The adapter's name.** `INPadapt` names the instance it injects `n_adapt<k>_`, `k`
counting from 1, and never asked whether the deck already had one. A deck with its own
`n_adapt1_` — an unrelated `chan` — beside a node the option split failed with

```
Error on line 9 or its substitute:
  n_adapt1_ x y chan
  device already exists, bail out
```

the user's line blamed for a name the option had taken.

**The batch measures.** `.option autocorner` runs a batch `.tran` at the nominal and at
every declared corner, and the `.meas` cards after each run, so

```
vmax = 3.33333e-01 at= 2.00000e-05    vend = 3.33333e-01
vmax = 2.83286e-01 at= 2.00000e-05    vend = 2.83286e-01
vmax = 3.86997e-01 at= 2.00000e-05    vend = 3.86997e-01
```

— one pair per corner in pass order, none labelled, where E-602 names each corner's
plot and `corners -output` names each row.

## What changed

- `INPadapt` picks the first `n_adapt<k>_` no line of the deck begins with
  (`adapt_name_taken`, case-folded, whole token); the adapters it injected earlier in
  the same pass are in the deck too and the counter never returns to their numbers.
  The debug line names the number chosen.
- `do_measure` prints `autocorner: measures at corner <name>` once before the first
  result of each run made under the option (`autocorner_corner_now()`, E-666's state
  of the running corner), and nothing on a plain run or in the `autostop` check.

## Verification

`autoadapt`: a deck with a user `n_adapt1_` beside a shared node adapts with
`n_adapt2_`, runs, and its six printed voltages equal the hand-written adapter's (was
"device already exists"). `autocorner` [16]: a batch `.tran` with two `.meas` cards
under the option prints three headers, `tt`, `ss`, `ff`, each before its own values,
which differ per corner; a plain batch run prints no header. On the E-722 binaries the
new checks fail. The other checks of both suites unchanged.

By hand: the hunt's two decks; the fourteen suites; the sweep.

## What this does not do

- A user instance named `n_adapt1_` *of the adapter model* is still taken for one of
  the option's own (E-467's idempotence rule) and left alone.
- The measure lines themselves are unchanged — a parser that reads `name = value`
  reads what it read — and the header goes to stdout only, not to the `.meas` output
  file.
- `.print` cards already carry the corner in their plot's name (E-602); nothing there
  changes.
