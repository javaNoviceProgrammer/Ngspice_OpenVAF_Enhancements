# Enhancement-581: `$track_plot` and `$track_hits` — a per-trial loop reaches its `track` result without naming the plot by number

**Scope:** `src/frontend/com_track.c` (the two variables), `docs/handbook/03-ngspice-workflows.md`
(the loop idiom and the `montecarlo` combination), `examples/track_examples/` (four
checks added, 40 per solver). **ngspice only.**

**Suites:** [`track_examples`](../examples/track_examples/) 40 of 40 per solver, both
solvers; full sweep 479 of 479.

## The question it answers

Does `track` (E-577) combine with a 1000-run Monte Carlo? Two routes, measured on an
RLC step response whose ringing peaks vary with a random resistor:

- **`montecarlo -expr` with the locators.** The functions behind `track` are ordinary
  `let` functions, so `montecarlo 1000 -analysis "tran 2u 1m" -expr
  npk=length(localmax(v(out))) -expr tpk=globalmax(v(out))` records a peak count and a
  peak position per sample into `montecarlo1`, on the fast path, with no loop. A
  vector-valued locator (`-expr xs=localmax(v(out))`) is recorded as an N × L family only
  when every sample has the same number of hits; otherwise E-552's rule refuses that
  expression with the reason and keeps the scalars beside it. This worked before this
  enhancement and is now documented in §3.6 of the handbook.
- **`track` itself, per trial.** `track` is a command, not an expression, so it goes in
  a `repeat` loop after the trial's analysis. That worked too, but the script had to name
  the result `track$&n` — and `track` numbers its plots by *successful* calls only, a
  miss makes no plot, so the numbering drifts as soon as one trial has no hits. In a
  test with a high prominence, every trial after the first miss collected the wrong
  plot's numbers. `montecarlo` avoids this for its own result with `$montecarlo_plot`;
  `track` exported nothing.

## What changed

After every `track`, **`$track_plot`** names the plot it made and **`$track_hits`**
holds the hit count. Both are cleared on entry — empty and 0 — so a refusal or a miss
never leaves the previous call's answer behind (the `hs_clear_results` rule of E-537).
The loop becomes:

```spice
repeat 1000
  reset
  tran 2u 1m
  set tp = $curplot
  track v(out) -spec localmax -prominence 20m
  if $track_hits gt 0
    setplot $track_plot
    let npk[n] = $track_hits
    destroy $track_plot
  end
  destroy $tp
  let n = n + 1
end
```

Two ngspice traps the handbook now names beside it, because both bit while testing: a
one-hit track has length-1 vectors, which the control language treats as scalars
(`time[0]` needs an `if $track_hits gt 1` guard), and a bare `>` inside `let` is output
redirection (write `gt`).

## Verification

The suite's new section runs six seeded trials with a prominence that makes some miss:
`$track_hits` and `$track_plot` are reported for every trial, a trial with hits names
a `track` plot and one without has an empty name and 0, the loop collects its counts
through `$track_hits` with no "no such plot" error, and a refusal after the loop (every
per-trial plot destroyed) leaves both cleared.
