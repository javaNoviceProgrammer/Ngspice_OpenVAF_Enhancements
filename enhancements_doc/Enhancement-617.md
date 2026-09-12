# Enhancement-617: the `savemc` workbook's header sets a model parameter's name in bold

**Scope:** `src/frontend/mcsave.c` — a column knows whether its parameter belongs to a
model card (`mcs_col.model`); the xlsx writer's `styles.xml` gains a bold font and a
second cell style, and the header row applies it to a model column's name
(`xlsx_str_cell_style()`); `MCSAVEparam()` takes the kind (`mcsave.h`), and the three
recorders supply it — `numparam/xpressn.c` (`mcs_slot_name()` reports a `.model` card's
slot), `com_sweep.c` (a fast-path bind's `mod`), `osdi/osdisetup.c` (`OSDImcSnapshot()`'s
callback gets `is_model`, `osdiitf.h`). `examples/savemc_examples/` grows 33 → 34
checks per solver; handbook [§3.6](../docs/handbook/03-ngspice-workflows.md), the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §8, the
suite README. **ngspice only.**

**Suites:** [`savemc_examples`](../examples/savemc_examples/) 34 of 34 per solver, both
solvers; `writemc`, `osdimc` green; full sweep 505 of 505.

## What was asked

A `savemc` file mixes two kinds of column — the draws a **model card** carries, shared by
every instance of the model (a `.model rm rstat r={agauss(1000,300,3)}` slot, `rm:r`; an
OSDI parameter declared without `type="instance"`, `@rm[r]`), and the draws an
**instance** carries on its own (`r1`, `n1:dr`, a subcircuit call's `x1.c`, an OSDI
mismatch parameter `@n1[dr]`) — and nothing in the header said which was which; the
`.param` names and the accessor spellings look alike. A quick visual cue in the
workbook was asked for: model parameters in bold, instance parameters in the regular
font.

## What changed

Every column records whether its parameter is a model card's. The kind is known where
each draw is recorded: the numparam expander's slot namer already recognises a `.model`
line (Enhancement-611) and now says so; a fast-path bind carries its tier
(`b->mod`); the OSDI snapshot's callback passes whether the owner is a model card or an
instance. The workbook's `styles.xml` declares two fonts — Calibri 11 regular and bold —
and two cell styles; the header row writes a model column's name with the bold style
and everything else (the three fixed columns, instance and `.param` columns, `writemc`
columns) unstyled.

```
trial  analysis  status  r1  x1.c  c.x1.c1  n1:dr  **rm:r**  @n2[dr]  @n1[dr]  **@rm[r]**
```

Read back with openpyxl: `('rm:r', True)`, `('@rm[r]', True)`, every other header
`False`. The csv and txt writers are unchanged (no formatting to carry); the data rows,
the 25-row rewrite cadence and the exit write are as before. A workbook written by an
older ngspice has one font and one style and still opens everywhere.

## Verification

| check | result |
|---|---|
| a deck with a `.param` draw, a device slot, a subcircuit call's value, an instance slot, an OSDI model parameter and two OSDI instance parameters, `savemc=Bold.xlsx` | `styles.xml` carries the bold font; the header cells `sm:r` and `@sm[r]` carry style 1, the nine others none |
| the same workbook through openpyxl (by hand) | `font.b` true for exactly those two names |
| the 33 existing checks (check [4]'s parser widened to accept a styled header cell) | unchanged |
| `savemc_examples` | 34 / 34, both solvers |
| full sweep | 505 of 505 |
