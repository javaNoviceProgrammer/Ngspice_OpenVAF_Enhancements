# Enhancement-217 — `pyplot -hist` (histogram plots)

The `pyplot` command ([E-94](Enhancement-94.md)) draws signals as traces versus their
scale — time, frequency, a swept parameter. Often, though, what you want is not the
waveform but its **distribution**: the amplitude spread of a transient, the histogram
of a Monte-Carlo measurement, the shape of a noise sample. E-217 adds a `-hist` flag
that renders each listed signal's *value* distribution as a histogram instead of a
trace.

```
pyplot -hist v(out)                  # one histogram
pyplot -hist v(a) v(b) v(c)          # overlaid, with a legend
pyplot mynoise -hist inoise_total    # named output
```

## How it works

`-hist` is a render *mode*, not a new analysis (unlike `-eye`, which folds a waveform
first). So the implementation is deliberately small and reuses the whole existing
`pyplot` pipeline:

- **`com_pyplot`** detects the `-hist` marker anywhere in the argument list, unlinks
  it, and dispatches the remaining `[name] signal-list` to `plotit` with a distinct
  device string, `pyplothist`.
- **`plotit`** resolves the signal expressions exactly as for a normal plot (so
  `v(out)`, `db(...)`, arithmetic on vectors, node names all work) and passes the
  resolved vectors to `ft_pyplot` with a `hist` flag.
- **`ft_pyplot`** writes the same `<file>.data` table and, when `hist` is set, emits
  `ax.hist(...)` per signal instead of `ax.plot(x, y)`.

Everything else the `pyplot` family already offers comes for free: the headless
`set pyplot_terminal=png|svg|pdf` render, `set pyplot_subplots=N` panels, style
sheets, figure size, and backend selection. Two histogram-specific knobs are added —
`set pyplot_hist_bins=<N>` (bin count; default matplotlib's `'auto'` rule) and
`set pyplot_hist_density` (normalize to a probability density).

A few details make it behave correctly rather than merely run:

- **The x-axis is the signal value, the y-axis is the count.** The panel labels are
  set accordingly (the value type — e.g. voltage — on x, "count"/"density" on y).
- **Panels do not share an x-axis.** A line plot's stacked panels share the
  time/frequency axis; histograms of *different* signals have unrelated value ranges,
  so `sharex=False`.
- **The full signal length is histogrammed.** The plot data table normally walks the
  shared *scale* vector, but a histogram of a raw `let` vector — a Monte-Carlo result,
  say — can have a scale whose length differs from the values'. The table now walks
  the longest *value* vector for a histogram (shorter ones pad with NaN, which the
  generated script filters), so nothing is silently truncated to the scale length.
- **Overlaid histograms are transparent; a single one is opaque.** Alpha is applied
  only when more than one histogram shares a panel.

## Verification (`examples/pyplothist_examples`)

`pyplothist_demo.cir` builds two signals with **closed-form** value distributions, so
the histogram is checked analytically, not just rendered: `ramp = i/(N-1)` is
**uniform** on [0,1] (a flat histogram), and `sine = sin(2πi/100)` is **arcsine** on
[-1,1] (U-shaped — a sinusoid dwells near its peaks, so the edge bins tower over the
middle). `verify_pyplothist.py` (6 checks, both solvers) parses the generated
`.data`/`.py` and PNG and confirms: the `-hist` path is taken (`plt.hist`, non-shared
x-axis); the full 20 000-sample length is histogrammed (not truncated to the scale);
the ramp is uniform (every bin within 15% of the mean); the sine is arcsine (edge
bins ≫ middle); and a valid PNG is produced. Full regression: 177/177.

## Scope

ngspice only, four files (`frontend/com_pyplot.c`, `frontend/plotting/pyplot.c` +
`.h`, `frontend/plotting/plotit.c`). No change to the ordinary `pyplot` trace path or
to `pyplot -eye`.
