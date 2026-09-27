# Enhancement-742: `writecorner`, and its short form `writecr` — `writemc` under the corner file's name, with every message under the name that was typed

**Scope:** `src/frontend/mcsave.c` (`wm_cmd`, `wm_msg`, `com_writecorner`, `com_writecr`; the
fourteen messages of `com_writemc` print through `wm_msg`, the usage line and
the nothing-recorded note name both recorders), `src/frontend/mcsave.h` (the
declaration), `src/frontend/commands.c` (the two entries, beside `writemc`),
`examples/savecorner_examples/` (five checks, [13]). **ngspice only.**
Requested by the user after the question whether a `writecorner` existed.

**Suites:** [`savecorner_examples`](../examples/savecorner_examples/) 34 of 34
per solver, both solvers (29 of 34 on the E-741 binary: the commands do not
exist there); `writemc`, `savemc`, `cornerscmd`, `autocorner` unchanged; full
sweep 532 of 532.

## What was asked

`.option savecorner` ([E-701](Enhancement-701.md)) is the corner twin of
`.option savemc`, and since E-701 the `writemc` command puts a value computed
after a run onto the last row of *both* files — on an `autocorner` combined
plot onto every corner's own row ([E-666](Enhancement-666.md)). There was no
`writecorner`: the corner workflow was written with a command named for the
Monte Carlo file. The user asked for the alias now, keeping the door open to
differentiate the two later, and then for a short form, `writecr`.

## What changed

`writecorner [name=]<expression> ...` is a second entry point,
`com_writecorner`, that sets the command name and calls `com_writemc`;
`writecr` is a third, `com_writecr`, the same under its shorter name. Nothing
in the recorder changes: the same values go onto the same rows, the same
refusals apply (`corner`, `status`, `analysis` and the other fixed columns),
the same per-corner evaluation runs on a combined plot.

What did change is that the handler now knows which name was typed. Its
messages went through a literal `writemc:` prefix; they go through `wm_msg`,
which prints the name in force, so a refusal after `writecorner corner=7`
reads

```
writecorner: `corner` is one of the savecorner row's fixed columns (corner, analysis, status)
```

and the dispatcher's own *too few args* refusal already carried the typed
name. Two texts were corrected on the way: the usage line says *savemc /
savecorner row*, and the nothing-recorded note — printed when neither
recorder is set, which has been its condition since E-701 — now says so:
*neither `.option savemc` nor `.option savecorner` is set*, where it named
`savemc` alone.

The help entries say what the aliases are: the same as `writemc` under the
corner file's name, one command serving both recorders today, the names kept
separate so they can diverge; `writecr` is described as short for
`writecorner`.

## Verification

Five checks in `verify_savecorner.py`, section [13], under both solvers:

* `writecorner vo=v(out)` after a plain run at `.option corner=ff` puts 0.5
  on that run's row beside `rsh = 88`;
* `writecorner corner=7 status=1` is refused twice under the command's own
  name, and nothing in the output says `writemc:`;
* on an `.option autocorner` combined plot, `writecorner vout=v(out)
  g=v(out)/v(in)` puts both values on every corner's row (`tt`, `ss`, `ff`),
  with the combined-plot note under its name;
* `writecr vo=v(out)` at `.option corner=ss` puts 0.5 on the row beside
  `rsh = 115`, `writecr corner=7` is refused under `writecr:`, and nothing in
  the output says `writemc:` or `writecorner`;
* with neither recorder set, the note names both options once, under the
  command's name; bare `writecorner` draws the dispatcher's refusal under its
  name.

On the E-741 binary the five fail: *no such command*. The
`writemc`, `savemc`, `cornerscmd` and `autocorner` suites are unchanged.

## What this does not do

* Nothing diverges yet. `writecorner`, `writecr` and `writemc` all write to
  whichever recorders are active; a value written by either lands on the savemc row and
  the savecorner row alike. Differentiating them (say, `writecorner` to the
  corner file only) is the future step the user named.
* `montecarlo -writemc` and `corners -mc N ... -writemc` keep their flag name;
  no `-writecorner` flag was added.
* The `savemc_writemc` font option, which styles the output column, keeps
  its name and applies to values written by either command.
