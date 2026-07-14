# Enhancement-189 — Sweep waveform overlay (`sweep … -overlay`)

A usability follow-up to the [Enhancement-146](Enhancement-146.md) `sweep` command. `sweep` steps any circuit knob — an instance parameter, a model parameter, a `.param`, a source value — runs an inner analysis at each point, and records **each output's last value** into a summary `sweep` plot (a transfer curve vs the knob). The individual per-point analysis plots are retained, but overlaying their full *waveforms* to compare shapes was a manual chore (`setplot` to each run, rename, `plot` one at a time). `-overlay` (alias `-ov`) does it in one step, producing the classic HSPICE `.step` overlay.

## The change

`sweep … -overlay` collects every point's **full output waveform**, resamples them onto a common independent-variable grid, and builds a single `sweepwave` plot with **one vector per (output, knob value)**, named `<output>_<value>`. The whole family then plots at once.

Three small static helpers were added to `frontend/com_sweep.c`:

- `sw_eval_vec(expr, &x, &y)` — evaluates the output expression and copies its **entire waveform** (not just the last value the summary keeps) plus its scale (the run's independent variable) into caller-owned buffers; a complex result (AC) is stored as magnitude.
- `sw_interp(x, y, len, xq)` — binary-search piecewise-linear interpolation, flat outside the data range. Each run lands on its own adaptive time/frequency grid, so the captured waveforms are resampled onto one shared grid before they can share a scale vector.
- `sw_wavename(base, val)` — builds a clean nutmeg vector name `<base>_<value>` (non-alphanumeric characters mapped to `_`).

In the sweep loop, when `-overlay` is set, each point's waveform and scale are captured alongside the existing last-value recording (the summary path is unchanged). After the loop, a common grid spanning `[min, max]` of all runs' scales is built at the finest run's resolution, every captured waveform is resampled onto it via `sw_interp`, and the results become the `sweepwave` plot — which is left current so `plot <out>_<val> …` works immediately.

## Correctness

The example is an RC low-pass (C = 1 nF) driven by a 1 V step, sweeping R so the time constant RC scales 1/2/4/8 µs. Each overlaid curve is the exact step response `v(out) = 1 − exp(−t/RC)`. The verification compares **every resampled sample of every curve** against that closed form and finds the worst error < 1e-4 — the resample is faithful, not merely visually close. Because the interpolation is piecewise-linear on the merged grid, it never overshoots a run's own endpoints.

## Scope and graceful degradation

`-overlay` is purely front-end and solver-independent — it reshapes vectors that already exist. When the inner analysis yields a scalar (an `op`, no waveform), there is nothing to overlay: it prints `-overlay ignored (analysis '…' has no waveform to overlay)` and produces the ordinary summary curve. It is never an error. Without `-overlay` the sweep path is byte-identical to Enhancement-146.

## Verification

[`examples/sweepwave_examples/verify_sweepwave.py`](../examples/sweepwave_examples/verify_sweepwave.py) — 5 checks: the `sweepwave` plot is built and the resampled family matches `1−exp(−t/RC)` to < 1e-4; each knob value gets a distinct `<out>_<val>` vector; `-overlay` is ignored gracefully on a scalar `op`; and the Enhancement-146 summary last-value curve is still recorded correctly (shared path). A [`sweepwave_demo.cir`](../examples/sweepwave_examples/) overlays four RC step responses and prints matching sample values. It is a front-end command, so it runs once (solver-independent). Full example regression: 153/153.
