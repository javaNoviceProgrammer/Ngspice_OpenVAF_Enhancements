# Enhancement-98 — `pyplot` multi-panel subplots and style sheets (version11)

Two additions to the Enhancement-94/95 `pyplot` command: **stacked subplots**
and **matplotlib style sheets**, both driven by `set` variables.

## `set pyplot_subplots=N` — stacked panels

By default `pyplot` draws every trace on one axis. Setting `pyplot_subplots=N`
lays the traces out as **stacked subplots sharing the x-axis**, `N` traces per
panel:

```spice
set pyplot_subplots=1
pyplot v(in) v(a) v(b)        ; three stacked panels, one trace each

set pyplot_subplots=2
pyplot v(a) v(b) v(c) v(d)    ; two panels, two traces each
```

The number of panels is `ceil(numtraces / N)`; the x-label appears on the
bottom panel, the title becomes the figure's suptitle, and each panel gets its
own grid, log scaling, limits, and legend. `0` (or unset) is the original
single-axis behaviour.

> **Note on `vs`.** In ngspice, `vs` already selects the x-axis vector
> (`plot y vs x`), and `pyplot` goes through the same `plotit()` expression
> parser — so `vs` is *not* a panel separator. Multi-panel layout is chosen
> with `pyplot_subplots` instead.

## `set pyplot_style=<name>` — matplotlib style sheets

`pyplot_style` applies a matplotlib style sheet to the whole figure, e.g.
`ggplot`, `bmh`, `seaborn-v0_8`. The short name `dark` aliases matplotlib's
`dark_background`:

```spice
set pyplot_style=dark
pyplot v(out)                 ; dark theme
```

An unrecognised style name is ignored (wrapped in `try/except`) rather than
aborting the plot.

## Implementation

All in `ft_pyplot()` (`src/frontend/plotting/pyplot.c`), which already has the
resolved trace list from `plotit()`:

- the figure is now always `plt.subplots(nrows, 1, sharex=True,
  squeeze=False)` (a uniform 2-D `axes`), with `nrows` computed from
  `pyplot_subplots`; each trace is assigned to `axes[i // N, 0]`;
- per-axis cosmetics (ylabel/grid/log/limits/legend) are emitted in a
  `for _ax in axes[:, 0]` loop; the x-label goes on `axes[-1, 0]` and the
  title on `fig.suptitle`;
- if `pyplot_style` is set, `plt.style.use(...)` is emitted before the figure
  (guarded).

## Verification

`pyplotpanel_examples` (5/5): a multi-RC transient rendered with
`pyplot_subplots=1` (three stacked panels), `pyplot_subplots=2` (two panels for
four traces), the default single axis, and `pyplot_style=dark` — the generated
scripts are checked for the right `plt.subplots(n, 1, …)` and
`plt.style.use('dark_background')`, and every case produces a valid PNG. Full
regression: 89 verify suites + 28 integration tests. Purely additive.
