# Enhancement-808: the currents `.options savecurrents` adds stay out of ac, sp and noise plots — they were empty there, or the bias point repeated per frequency

**Scope:** D14 and D15 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `frontend/inp.c`: `inp_savecurrents` writes its per-device saves as `.savecur` lines.
- `frontend/dotcards.c`: `ft_dotsaves` registers them after the deck's own `.save` lines, with
  the savecurrents mark; `ft_cktcoms` knows `.savecur`.
- `frontend/breakp2.c`: `ft_save_mark_auto` keeps the mark's value.
- `include/ngspice/ftedefs.h`: `SAVE_AUTO_INFERRED`, `SAVE_AUTO_SAVECURRENTS`.
- `frontend/outitf.c`:
  - `beginPlot` leaves marked saves out of a frequency-domain analysis' plots, with one note;
  - E-496's and E-725's silences test for the inferred mark only.

`examples/osdislips_examples/` (section [14], six checks). **ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 93 of 93 per solver (3 of the 6
in [14] fail on the E-795 binaries); the full sweep, 538 of 538.

## What was wrong

`.options savecurrents` adds a `.save` of every device's terminal currents. Those are op, dc and
tran quantities. Outside those analyses they meant nothing, in three ways:

- **D14, ac (and sp), built-in devices.** A built-in device's ask refuses a current in an ac
  analysis (`E_ASKCURRENT`). The plot held `@c1[i]` and `@d1[id]` 0 long, and
  `print @c1[i] i(v1)` failed whole with `vector @c1[i] is not available`.
- **ac and sp, OSDI devices.** `@n1[i]`, `@n1[i_a]` and `@n1[i_b]` were recorded as the DC bias
  current, real and flat at every frequency, in a complex plot: the hunt's F19.
- **D15, noise.** Both noise plots (`noise1`, `noise2`) carried `@rs[i]`, `@c1[i]` and
  `@n1[i_a]` as the bias current repeated per frequency, typed "current" beside noise densities,
  for built-in and OSDI devices alike.

## The change

The saves `savecurrents` adds now carry their origin. `inp_savecurrents` writes them as
`.savecur` lines, and `ft_dotsaves` registers them after the deck's `.save` lines, marked
`SAVE_AUTO_SAVECURRENTS`. A name both give keeps the deck's save, unmarked.

`beginPlot` leaves the marked saves out of these analyses: `ac`, `noise`, `sp`, `disto`, `hb`,
`pz` and `sens`. It says so once per analysis; the integrated-noise plot stays quiet:

```
Note: .options savecurrents saves device currents in op, dc and tran analyses; this AC analysis leaves its 6 out (they would hold nothing, or the bias currents). For a small-signal current, use `.probe i(<device>)`.
Note: .options savecurrents saves device currents in op, dc and tran analyses; this NOISE analysis leaves its 6 out (they would hold the bias currents, repeated at every frequency).
```

`.probe i(c1)` inserts a 0 V source and records the true ac current. The suite's RC checks it
against the source current.

Unchanged:
- op, dc, tran (and pss, tf) record the currents as before;
- a `.save @r1[i]` the deck writes itself is kept in every analysis, as before;
- E-496's "inferred save" silences test for the inferred mark only, so savecurrents' saves warn
  as plain `.save` lines did.

## The checks

osdislips [14]:

- ac: no savecurrents vector, for the built-in and the OSDI device;
- ac: one note, with the `.probe` hint;
- noise: none in either noise plot, said once;
- op and dc keep them;
- an explicit `.save @r1[i]` in ac is kept, without the note;
- the `.probe i(<device>)` the note suggests records the ac current: i(r1) = -i(v1) = i(c1),
  non-zero.

## Limits

- An explicit `.save @n1[i_a]` of an OSDI device in an ac analysis still records the bias
  current. That, and a true small-signal terminal current for OSDI devices, is the hunt's F19,
  still open. This change removes only the route by which `savecurrents` put such vectors into
  every ac plot.
- `print @c1[i]` after an ac now reads the device directly (the vector is not in the plot), and
  shows its present operating-point value, as it does with no `savecurrents` at all.
