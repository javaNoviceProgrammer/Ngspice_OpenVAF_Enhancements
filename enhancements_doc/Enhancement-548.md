# Enhancement-548: `pyplot` writes exact data, honours `ylimit` under `ylog`, gives mixed units two scales, and its script runs from anywhere

**Scope:** defects 3 to 6 of the `pyplot` review recorded in
[E-547](Enhancement-547.md). **ngspice only; the compiler is unchanged.**

**Suites:** [`pyplot_examples`](../examples/pyplot_examples/) 24 → 29 (two
existing checks updated for the new script text); the twelve suites that
exercise pyplot pass.

## What was wrong, and what changed

* **Six significant digits.** The data table was written with `%e`, in the
  file the reference calls the export. A time axis offset to 1 s with 1 ns
  steps collapsed to *one* distinct x value in 59 rows; a 1 V signal with a
  microvolt ripple collapsed to eight levels. Every table is now written with
  17 significant digits (`PY_NUM`), which round-trips every double.
* **`ylimit` under `ylog`.** `ylimit 1e-3 1 ylog` set the log scale and
  silently no limits, because of a `!ylog` guard. The limits are applied now.
  A non-positive bound never reaches the backend — plotit refuses it first
  with *Y values must be > 0 for log scale* — so the backend's own check for
  that case is a backstop.
* **Mixed units.** `pyplot v(out) i(v1)` put a volt-scale trace and a
  milliamp trace on one axis and emitted no y label at all (plotit hands
  over none for a mixed list), so the current lay flat along the bottom.
  Stock `plot` gives each type its own scale; so does this now: within a
  panel the first trace's type owns the left axis and any other type is
  drawn on a `twinx()` axis on the right, each labelled with its type, the
  legends combined, and every trace given an explicit colour — a twin axis
  restarts matplotlib's colour cycle, so the two first traces would both have
  come out blue. `ylimit`, `ylog` and the reference lines apply to the left
  axis; with `pyplot_subplots` the rule holds per panel.
* **A relocatable script.** The script loaded `'look.data'` relative to the
  directory ngspice ran in, so the reference's own advice — edit the script
  and run it again — failed from anywhere else. It now resolves its data
  table and its image against its own location (`_here`).

## Verification

| check | result |
|---|---|
| a 1 s-offset, 1 ns-step axis | every x distinct (was 1 of 59) |
| a 1 µV ripple on 1 V | survives (was 8 levels) |
| `ylimit 1e-3 1 ylog` | `set_ylim(0.001, 1)` emitted |
| `ylimit 0 1 ylog` | refused by the command, no script |
| `v(out) i(v1)` | `twinx()`, `V` left and `A` right, one legend, `C0`/`C1` |
| the script run from another directory | succeeds, image beside the script |
| `pyplot_examples` | 29 / 29, both solvers |
| full sweep | 455 of 455 |
