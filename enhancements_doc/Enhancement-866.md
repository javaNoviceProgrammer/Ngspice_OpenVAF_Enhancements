# Enhancement-866: a pz plot's vectors keep their names in `write` and `print all` — `v(zero(1))`, a duplicate `v(all)` and `all = …`

**Scope:** F11 of the
[third robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

ngspice:
- `frontend/rawfile.c`, `raw_write`: a name of the form `f(...)` is not wrapped in `v(...)`.
- `frontend/evaluate.c`, `ft_evaluate`: a single vector found by `all`, `allv`, `alli`, `ally`
  or `alle` keeps its own name.

`examples/pzwrite_examples/` (new). **ngspice only.**

**Suites:**
- [`pzwrite_examples`](../examples/pzwrite_examples/): 6 of 6 per solver. On the E-863 binaries
  4 fail; [5] and [6] are controls.
- The full sweep: 571 of 571.

## What was wrong

`display` after `pz` shows `pole(1)` and `zero(1)`. Two things went wrong after that.

**`write` wrapped the roots' names.** It writes a voltage-typed vector as `v(name)` unless the
name is already a node voltage or the plot's scale. A pz plot's roots are voltage-typed, so
every root after the scale was written `v(zero(1))`, `v(pole(2))`. The file loaded back under
those names, not its own.

**`all` renamed a lone vector.** `all` names the list of a plot's vectors. On a plot that holds
one, the list is that one vector, and `ft_evaluate` named the result after the expression, as it
does for any single result. So on a pz plot with one pole:
- `print all` printed `all = -1.5e+06,0`;
- `write` wrote the pole twice, as `pole(1)` (the scale) and as `v(all)`.

## The change

- `raw_write` leaves a name that already has the form `f(...)` as it is. A node voltage is
  `v(name)` internally and an op plot is written as before (`v(1)`, `i(v1)`).
- `ft_evaluate` does not rename a single result whose expression is one of the `all` words. The
  vector keeps its name: `print all` prints `pole(1) = …`, and `write` writes one variable,
  `pole(1)`.

A script that read a lone root as `all = …` reads `pole(1) = …` (or `zero(1) = …`) now; the same
holds for `print all` on any plot that holds one vector. Six of this project's suites read the
old form (analyses, klupz, osdislips, pzhb, saveguard and stdaudit) and now read both.

## The checks

`pzwrite_examples`:
- **[1]** `write` of a plot with a pole and a zero: `pole(1)` and `zero(1)`.
- **[2]** `write` of a plot with one pole: one variable, `pole(1)`, no `v(all)`.
- **[3]** `print all` on that plot prints `pole(1) = …` (`all = …` on E-863).
- **[4]** The written file loads back under its own names.
- **[5]** (control) An op plot still writes `v(...)` and `i(...)` names.
- **[6]** (control) `print all` on a plot with several vectors names each.
