# Enhancement-341 — `sweep -analysis reset` / `-analysis remcirc` SIGSEGV'd

Found by fuzzing the `sweep` and `optimize` commands.

```
sweep pr lin 3 1k 3k -analysis reset   -output v(out)   ->  SIGSEGV
sweep pr lin 3 1k 3k -analysis remcirc -output v(out)   ->  SIGSEGV
```

## Root cause

`sweep` runs its `-analysis` argument as a command at every point, dispatched by
name through `sw_run_cmd`. Nothing stopped a user naming `reset` or `remcirc` —
which free and rebuild, or remove, the very circuit the sweep is iterating over.
The loop then carried on with its resolved knob bindings, the old
`CKTcircuit *` and the old plot.

## Why the fix rejects up front rather than recovering

The obvious repair — notice the circuit changed and break out of the loop — was
tried first **and made things worse**. The sweep's post-loop plot finalisation
touches the same freed state, so breaking out simply moved the crash; and it
turned a previously *working* case, `-analysis 'optimize ...'` (which resets
internally but re-establishes its own state), into a new crash. That attempt was
reverted.

Rejecting a destructive analysis before the loop starts cannot regress anything,
and nothing legitimate is lost: a sweep re-sources the deck itself when a knob
needs it, so a user `reset` in the per-point analysis has no purpose.

```
sweep: -analysis 'reset' would destroy the circuit the sweep is iterating over;
use a real analysis (op, dc, ac, tran, ...). The sweep re-sources the deck
itself when a knob needs it.
```

`optimize` is deliberately **not** rejected — it resets internally, recovers, and
works today.

## The fuzz campaign

Enhancement-270 already fuzzed `sweep`'s numeric bounds, so this extended the
strategy rather than repeating seeds.

**Round 1 — argument surface: 684 invocations, clean.** 20 knob kinds (instance
param, `@model[param]`, `.param`, the E-268/269 wildcards `@*[p]` / `@#*[p]` /
`@*[[p]]`, and malformed `@`-forms) crossed with 29 sweep specifications
(`start stop step`, `lin|dec|oct N start stop`, `list`, plus missing, reordered
and non-numeric variants), 31 option shapes, and 51 `optimize` invocations
covering all seven methods (`nm lm pso de sa nsga nsga2`), all three knob kinds
(`-param -mparam -dparam`), every objective form, and algorithm knobs at
degenerate values.

**Round 2 — recursion and state: this is where the bugs were.** Both commands
take another *command* as an argument, which makes them self-referential, and
both carry state between invocations. 23 cases: sweep inside sweep (including the
same knob, and three deep), optimize driving a sweep and vice versa, repeated
sweeps into one plot, `-overlay` accumulation, `-warm` with and without a prior
run, fast-path and reset-path knobs alternating, and the analysis mutating the
circuit under the loop.

## Verified

Both crashes are refused cleanly; a real analysis still sweeps and records the
right number of points; `-analysis 'optimize ...'` still works; and round 1's 684
invocations remain clean.

## Also found, characterised, NOT fixed here

A sweep near the `SW_MAXPTS` cap looks like a hang because point cost grows with
point count — measured **171 us/point at 1000, 761 at 5000, 2994 at 20000**: 20x
the points for 300x the time, i.e. roughly quadratic.

Profiling puts it in `DCop -> OUTpBeginPlot -> cp_getvar -> cp_usrvars ->
cp_enqvar -> dup_string`. `cp_getvar` materialises the *entire* user-variable
list, allocating a duplicated string per entry, and that list grows with the
plots a long sweep accumulates. `OUTpBeginPlot` calls it once per analysis for
`printinfo` and `interp`.

Making the construction lazy was tried and **measured to give no improvement** —
those two variables are normally unset, so the search falls through to the
materialised list anyway — and was reverted rather than shipped unmeasured. A
real fix means making `cp_usrvars()` cheap or caching it with proper
invalidation, which is a general ngspice change well outside a crash fix. It is
recorded here with its measurements so it does not have to be rediscovered.

## Files

- `ngspice-46/src/frontend/com_sweep.c` — reject a destructive `-analysis`.
- `examples/sweepanalysis_examples/` — both shapes refused, real analyses and
  internally-resetting ones still work (`verify_sweepanalysis.py`, 5 checks).
