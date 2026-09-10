# Enhancement-594: `.option saveused` no longer refuses a noise or sp analysis, and `save S_2_1` matches the vector it names

**Scope:** `src/frontend/dotcards.c` (`ft_saveused`), `src/frontend/outitf.c`
(`name_eq`), `src/frontend/breakp2.c` (`save_already_present` in `ft_getSaves`),
`examples/savenoise_examples/` (new, 11 checks per solver). **ngspice only.**
Finding F1 of the 2026-09-09 dig into `autobus`, `autoadapt`, `automc` and
`saveused`, plus two slips found under it.

**Suites:** [`savenoise_examples`](../examples/savenoise_examples/) 11 of 11 per
solver, both solvers; `saveused`, `saveforms`, `autoopts`, `savecur`, `savecuroff`,
`savekw`, `hiernode`, `namelookup` unchanged; full sweep 489 of 489.

## What was wrong

`.option saveused` (Enhancement-469) reads the control block and the deck's output
cards before the run and saves what they mention; nothing else. Its one promise is
that the deck still works. A noise analysis broke it on every deck:

```
.option saveused
.control
noise v(out) v1 dec 2 100 10k
print noise2.onoise_total
.endc
```

```
Error: no data saved for Noise analysis; analysis not run
```

A noise run's plots hold `onoise_spectrum`, `inoise_spectrum`, the totals and, when
asked for, the per-generator contributions — and no node. The scan took `out` from
the `noise v(out) v1 ...` line itself, so the inferred list could never name anything
the analysis publishes, and `beginPlot` refused the analysis outright. A `.noise`
card run through `run` failed the same way. Stock ngspice says the same to a
hand-written `save out` before a noise run; the author of that line can see it, the
author of this option wrote no such line.

An sp analysis was in the same position and worse. Its plot holds `S_i_j`, `Y_i_j`,
`Z_i_j` and `Rbase`, so `wrs2p` beside a `print v(in)` had nothing to write. And
`print S_2_1` failed even though the scan had registered that very name: the deck
reader lowercases a `save` name, the analysis publishes `S_2_1` in mixed case, and
`name_eq` compared with `strcmp`. Stock ngspice has that one too — `save S_2_1`
before `sp` answers "nothing of that name is in this analysis" while `print S_2_1`
finds the vector, because `findvec` already compares without case.

A third slip surfaced in the fix. Enhancement-417 added a dedup to `ft_getSaves` so
its `@dev[i_p]` expansion would not register a name the deck also wrote; it compared
names alone, so a second `save all` that differed only in its analysis restriction
was dropped. `settrace` never merges `all` at insert time for exactly that reason.

## What changed

- **The option saves everything for a noise or sp analysis.** Whenever it acts,
  `ft_saveused` also registers a `save all` restricted to `NOISE` and one restricted
  to `SP`. `beginPlot` marks a save restricted to another analysis as used and moves
  on, so a transient or ac beside them is pruned exactly as before, and what the two
  analyses build is a frequency sweep of a handful of vectors — nothing the option
  was made to shed. Registered whenever the option acts rather than on sight of a
  `noise` line, because the analysis can also arrive through a `.noise` card and
  `run`, or a loop the scan cannot follow. Stock semantics are untouched: an explicit
  `save out` before `noise` still refuses the run, and `save in` before `sp` still
  drops `S_2_1`, since an explicit list is obeyed.
- **`name_eq` compares without regard to case**, so a saved name matches the
  mixed-case vector an analysis publishes (`S_1_1`, `Y_1_1`, `Z_1_1`, `Rbase`, `NF`,
  `SOpt`, `NFmin`, `Rn`). Node names are lowercase throughout, so nothing that matched
  before matches differently now. The Enhancement-428 hierarchical spelling takes the
  same comparison.
- **`save_already_present` respects the analysis restriction**: the same name for two
  different analyses is two requests. Both `all` entries survive `ft_getSaves`.
- The `ngdebug` line now reads "saveused: N vector(s) kept; a noise or sp analysis
  keeps everything (its plot holds no node)".

## Verification

| check | result |
|---|---|
| `noise v(out) v1 dec 2 100 10k` under the option | runs; `onoise_total` 1.82989251e-07, equal to the unrestricted run |
| the per-generator form (`pts_per_summary`) | the noise1 vector set is identical to the unrestricted run's, `onoise_r1_thermal` included |
| a `.noise` card run through `run` | runs, total printed |
| `ac lin 1 1k 1k` + `print v(out)` beside the noise run | the ac plot holds `out` alone; `in` and `s` are not saved |
| `sp lin 3 1k 10k` + `print v(in)` + `print S_2_1` + `wrs2p` under the option | `S_2_1` prints, the plot holds every S/Y/Z entry and `Rbase`, the `.s2p` file has three data rows |
| stock, `save S_2_1 in` before `sp` | matches: plot is `S_2_1`, `in`, `frequency`; no "nothing of that name" |
| stock, `save in` alone before `sp` | `S_2_1` still absent — an explicit list is obeyed |
| stock, `save out` before `noise` | still "no data saved for Noise analysis", as it always did |
