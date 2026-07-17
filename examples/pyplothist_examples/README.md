# pyplothist_examples — Enhancement-217: `pyplot -hist`

`pyplot -hist <sig> ...` renders each signal's **value distribution** as a histogram
(matplotlib `plt.hist`) instead of a trace versus time or frequency:

```
pyplot -hist v(out)                  # one histogram
pyplot -hist v(a) v(b) v(c)          # overlaid, with a legend
pyplot mynoise -hist inoise_total    # named output (mynoise.py/.data/.png)
```

It reuses the entire `pyplot` pipeline ([E-94](../../enhancements_doc/Enhancement-94.md)
onward) — the matplotlib back end, `set pyplot_terminal=png|svg|pdf` for a headless
render, `set pyplot_subplots=N` for panels, styles, figure size, backend — so only
the render changes. Two histogram knobs are added: `set pyplot_hist_bins=<N>` (bin
count; default matplotlib's `'auto'`) and `set pyplot_hist_density` (normalize to a
density). Where signals are overlaid on one axis they get alpha transparency and a
legend; a single histogram is drawn opaque.

Typical uses: the amplitude distribution of a transient waveform, the spread of a
Monte-Carlo measurement, or a noise sample.

## The demo

`pyplothist_demo.cir` builds two signals with **known analytic distributions** so the
histogram can be checked, not just rendered:

- `ramp = i/(N-1)` → **uniform** on [0,1] (a flat histogram);
- `sine = sin(2πi/100)` → **arcsine** on [-1,1] (U-shaped — a sinusoid dwells near its
  peaks, so the edge bins tower over the middle).

## What is verified

`verify_pyplothist.py` (6 checks, both solvers) parses the generated `.data`/`.py` and
the PNG:
1. the `-hist` path is taken (`plt.hist`, not `plt.plot`; panels do not share an
   x-axis);
2. the full signal length is histogrammed — a raw `let` vector whose scale length
   differs must not be truncated (the E-217 data-table fix);
3. the ramp histogram is **uniform** (every bin within 15% of the mean);
4. the sine histogram is **arcsine** (edge bins ≫ middle bins);
5. a valid, non-trivial PNG is rendered.

## Run

```sh
python3 verify_pyplothist.py
```
