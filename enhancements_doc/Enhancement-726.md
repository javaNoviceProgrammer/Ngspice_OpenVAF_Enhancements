# Enhancement-726: under `.option saveused`, a plot-qualified bare name (`print tran1.out`) also saves the vector after the dot, and a save set the option inferred that names nothing an analysis produces keeps everything of that analysis, said once, instead of refusing it — one cross-plot reference had turned the `op` and the `tran` before it off, and a `pz` beside a `print v(out)` was refused because no block names `pole(1)` by a form the scan reads

**Scope:** F4 of the
[five-options dig of 2026-09-25](../docs/bug_hunts/2026-09-25_five-options-dig.md).
**ngspice only.** `src/frontend/dotcards.c` (`e469_add_name`, used by the bare-word
scan, the expression scan and the `$&` scan), `src/frontend/outitf.c` (`beginPlot`:
`all_inferred`, the kept-whole plot beside [E-603](Enhancement-603.md)'s).
[`examples/saveused_examples/`](../examples/saveused_examples/) (section E-726, 4 checks,
44 per solver). Handbook [§3.7](../docs/handbook/03-ngspice-workflows.md). The hunt
page.

**Suites:** `saveused` 44 of 44 per solver, both solvers (34 of 44 on the E-722
binaries, with [E-727](Enhancement-727.md)'s checks); `saveforms` 16 of 16, `autocorner`
26 of 26 with [E-725](Enhancement-725.md), `savekw` 46 of 46, `savenoise` 11 of 11,
`multisave` 9 of 9, `savemiss` 11 of 11, `saveguard`, `autosave`, `savecur`,
`savecuroff`, `savecorner`, `autoopts` 43 of 43, `savemc`, `reusedev` unchanged; no new
build warnings; full sweep, run alone.

## What was wrong

The RC divider, `.option saveused`, and

```
op
tran 0.1u 1u
print tran1.out
```

```
Error: no data saved for D.C. Operating point analysis; analysis not run
Error: no data saved for Transient analysis; analysis not run
Warning from checkvalid: vector tran1.out is not available or has zero length.
```

`print op1.v(out)` in the same place worked (the `v()` form collects `out`). The bare
word `tran1.out` — ngspice's own cross-plot spelling, the vector `out` of the plot
`tran1` — went into the save set as a name; no analysis produces a vector called that,
so the set matched nothing, and `beginPlot` refuses an analysis whose saves match
nothing ("no data saved"). Both analyses were skipped, under an option whose one
promise is that the deck still works ([E-469](Enhancement-469.md)).

The same refusal reached a `pz`: `op` / `print v(out)` / `pz in 0 out 0 vol pz` /
`print pole(1)` was "no data saved for pole-zero analysis; analysis not run" and then
"no such function as pole" — the set held `out`, the pz plot holds `pole(1)` and
`zero(1)`, and no control block names those by a form the scan reads.
[E-594](Enhancement-594.md) had met the same shape on `noise` and `sp` and registered a
`save all` for those two analyses by name; every other analysis whose plot the scan
cannot name was still refused.

## What changed

**A bare name with a dot registers both spellings** (`e469_add_name`): the whole name,
which is what a subcircuit node needs (`x1.out` is a node spelled the same way, and the
scan cannot tell a plot prefix from an instance path), and the part after the last dot,
which is what the plot-qualified form needs. The one that matches nothing is inferred,
so it costs a slot and warns about nothing ([E-496](Enhancement-496.md)). The rule
applies to a bare word on an output command, to a name inside an expression and to a
`$&name` ([E-727](Enhancement-727.md)).

**An inferred set that names nothing of an analysis keeps everything of it**
(`beginPlot`). The refusal is right for a hand-written save: the author asked for
something the analysis has not got, and [E-493](Enhancement-493.md) names it. A set
`.option saveused` inferred is the scanner's guess at the control block, and a guess
that names nothing an analysis produces is a blind spot of the scan, not a request to
run the analysis for nothing. When every save that applies to the analysis is an
inferred one (`autosaved`, E-496's mark), none of them matched, and the plot has
vectors, the analysis keeps every vector — the path E-603 takes for a plot within a
sequence — and says so once:

```
saveused: nothing the control block names is in the pole-zero analysis; everything of it is kept
```

The memory the option was set to save is what a reader would miss, so the note is not
optional. A hand-written `save nosuch` before an `op` is refused exactly as before, and
E-594's `save all` for `noise` and `sp` stays: those two are known, this is the net
under every other.

## Verification

`saveused` section E-726: `op` / `print dc1.out` keeps `out`, runs both analyses and
prints the cross-plot value; a `pz` beside `print v(mid)` is kept whole, said once,
`pole(1)` prints its pole, and the operating point — which the set does name — is not
said; a hand-written `save nosuch` still refuses the analysis with no note. On the E-722
binaries the first two fail as the hunt saw, the last two pin what was already so.

By hand: the hunt's harness D [D3] and [D4] on both binaries; a subcircuit node
`x1.mid` printed bare and read in a `let` (E-727's check); the fourteen suites; the
sweep.

## What this does not do

- It does not decide which analysis a name belongs to. `tran1.out` saves `out` for
  every analysis of the run, as `v(out)` would; the option never restricted a save by
  analysis and does not start now.
- It does not touch a mixed set: one hand-written save beside the inferred ones, or a
  `.probe`, keeps the old refusal when nothing matches — the author wrote a line, and
  E-493 speaks to it.
- The note goes to stdout, once per analysis that is kept whole, not to the raw file.
