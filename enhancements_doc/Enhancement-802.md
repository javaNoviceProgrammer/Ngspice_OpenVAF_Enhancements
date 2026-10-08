# Enhancement-802: a batch run whose .control block ran the analyses prints each `.meas` once — and a `.meas` result is a vector, as the `meas` command's is

**Scope:** D8 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `main.c`: the batch epilogue skips its `run` when it has nothing new to run.
- `frontend/spiceif.c`: new `if_deck_run_pending`; `ci_deck_ran` is set by a successful `run`
  and cleared when the deck's task is created.
- `include/ngspice/ftedefs.h` (`ci_deck_ran`) and `include/ngspice/fteext.h`.
- `frontend/measure.c`: new `meas_card_vector`, called for each card measurement and each
  `param`/`expr` one.

`examples/osdislips_examples/` (section [8], eight checks). **ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 56 of 56 per solver (4 of the 8
in [8] fail on the E-795 binaries); the full sweep, 538 of 538.

## What was wrong

```
.meas tran vmax max v(1)
.control
tran 1n 2u
print vmax
.endc
```

run with `ngspice -b` printed "Measurements for Transient Analysis" and `vmax = 2` twice. The
first came after the `tran`, as it should; the second at exit. The batch epilogue runs the deck
(`ft_dorun`) whenever it carries a `.print`, `.plot`, `.four`, `.meas`, `.op` or `.tf` card. This
deck had no analysis card, so that `run` had no job. It still printed "Doing analysis at TEMP"
and measured the plot already measured.

A deck with its own `.tran` and a `run` in its `.control` block fared worse: the epilogue ran the
same analysis a second time, and measured it again.

And `print vmax` said "vector vmax is not available". A `.meas` card's result went to the
numparam table only, for later `param` measurements. The `meas` command stores its result as a
vector of the current plot, so the card and the command disagreed.

## The change

**The epilogue.** It skips its `run` when the `.control` block ran simulations (`sim_status` 0)
and either the deck has no analysis card of its own, or a `run` in the block already ran it.
`.print`, `.plot` and `.four` output still follows, from the plots that exist. A deck whose
`.tran` card never ran, beside a `tran` command in the block, still gets its run: the deck asked
for two analyses.

**The vector.** Each card measurement that succeeds stores its result in the plot it measured,
as `meas` does: `print vmax`, `let x = vmax*2`. A failed one drops a previous result of the same
name, E-475's rule for `meas`. A name the plot already holds as simulation data is left alone: a
vector longer than one point, a typed vector, or the scale. So `.meas tran out max v(out)` does
not replace node `out`.

## The checks

osdislips [8]:

- the block runs the analysis and the deck has none: measured once, one "Doing analysis";
- `print vmax` is 2 and `let x = vmax*2` is 4;
- a `.tran` card and `run` in the block: run once and measured once (it was twice each);
- a card and no `.control` block: once, as before;
- a `.print` card still prints its table after the block's `tran`;
- a deck `.tran` beside a block `tran`: both run, as before;
- a failed measurement leaves no vector;
- a result named like a node leaves the node's vector whole.

## Limits

- A block that does `run`, then `alter`, and relies on the epilogue to run the deck again with
  the new value no longer gets that second run. The `.print` table comes from the block's run.
  Add a `run` after the `alter` for the old effect.
