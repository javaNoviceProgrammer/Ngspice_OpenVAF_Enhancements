# Enhancement-602: two dot cards naming one vector for different analyses keep both analyses, and a batch run evaluates every analysis's `.meas` cards

**Scope:** `src/frontend/breakp2.c` (`settrace`'s dedup), `src/frontend/runcoms.c`
(`dosim`, the measures of every analysis a run produced), `src/frontend/measure.c` (the
header), `examples/multisave_examples/` (new, 9 checks per solver). **ngspice only; the
batch flow is shared by every device.** Finding N6 of the 2026-09-10 integration hunt
([`docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md`](../docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md)),
a stock ngspice defect.

**Suites:** [`multisave_examples`](../examples/multisave_examples/) 9 of 9 per solver,
both solvers; every suite that reads measures (`measparam`, `measwindow`, `measavgwin`,
`measovf`, `acmargin`, `argguard`, `autoopts`, `corenum`, `malftoken`, `opvar`,
`saveforms`, `stdaudit`) unchanged; full sweep 496 of 496.

## What was wrong

```
.dc v1 0 1 0.5
.tran 10u 1m
.print dc v(a)
.print tran v(a)
```

```
Error: no data saved for Transient analysis; analysis not run
```

Swap the two cards and it is the dc that is not run. `ft_savedotargs` registers each
card's vectors as a `save` restricted to the card's analysis; `settrace` refused a second
`save` of a node name it already held, without looking at the restriction, so `a` stayed
restricted to DC and the transient's `beginPlot` found nothing to save. A `.meas` card
registers its vectors the same way, so `.meas dc vmax max v(a)` beside a `.tran` — a
common deck — silently lost the transient, and beside a `.dc` a `.meas tran` lost the
dc. Enhancement-594 made the dedup in `ft_getSaves` respect the analysis; this was the
same defect one level up, at insert time.

Two more sat behind it in the batch flow. After a `run` with several analysis cards,
`dosim` called `do_measure` for the **last** analysis only, and `do_measure` skips every
card whose type is not the one named — so once both analyses ran, the other one's
measures were still skipped in silence. And the "Measurements for ... Analysis" header
was chosen by the *first card's* type before that card was matched against the analysis
being evaluated, so it named the wrong analysis, or stood over nothing.

## What changed

- **One save per name *and* analysis.** `settrace` treats a repeat as a repeat only for
  the same analysis, or when an unrestricted save already covers every analysis. `.save
  v(a)` followed by `.print tran v(a)`, and two `.print tran` cards on one vector, are
  still one save each.
- **Every analysis's measures.** `dosim` remembers where the plot list stood before the
  run, and afterwards evaluates the `.meas` cards of each `tran`, `dc`, `ac` or `sp` plot
  the run produced, on that plot, in the order the analyses ran, leaving the last plot
  current as before. A run that produced one plot goes through the old call unchanged.
- **The header names the analysis being evaluated**, and is printed only when one of its
  cards is about to run.

## Verification

| deck | before | now |
|---|---|---|
| `.print dc v(a)` + `.print tran v(a)`, either order | the second analysis "not run" | 3 and 108 rows, both tables |
| `.meas dc vmax max v(a)` beside `.tran` | the transient not run | both run; `vmax` = 1 under "Measurements for DC Analysis" |
| `.meas tran tmax max v(a)` beside `.dc` | the dc not run | both run; `tmax` = 0.9998 under "Measurements for Transient Analysis" |
| both measures | one header, one value, one header over nothing | two headers, two values |
| dc, tran and ac with a measure each | one value | three headers, three values |
| `.save v(a)` then `.print tran v(a)`; two `.print tran` cards on one vector | one save each | unchanged |
| the same shapes with OSDI devices | as above | both analyses, both measures |

Full sweep 496 of 496 on both solvers.
