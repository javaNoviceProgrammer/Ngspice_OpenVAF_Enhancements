# Sweep waveform overlay — `sweep … -overlay` (Enhancement-189)

The `sweep` command (Enhancement-146) steps any circuit knob — an instance
parameter, a model parameter, a `.param`, a source value — runs an inner
analysis at each point, and records **each output's last value** into a summary
`sweep` plot (a transfer curve vs the knob). The per-point analysis plots are
kept, but overlaying their full waveforms to compare shapes was a manual chore
(`setplot`, re-name, `plot` one at a time).

`-overlay` (alias `-ov`) does it in one step: it collects every point's **full
output waveform**, resamples them onto a common independent-variable grid — the
runs land on different adaptive time/frequency grids, so a shared axis is
required — and builds a single `sweepwave` plot with **one vector per (output,
knob value)**, named `<output>_<value>`. The whole family then plots at once,
the classic HSPICE `.step` overlay.

```
sweep R1 list 1k 2k 4k 8k -analysis tran 5n 8u -output vout=v(out) -overlay
```
```
sweep: 4 points into the 'sweep' plot; `plot <output>` to view vs r1.
sweep: overlay of 4 waveforms per output resampled to 1618 points in the
       'sweepwave' plot (now current); `plot <output>_<val> ...` to view.
```

The `sweepwave` plot is left current, so `plot vout_1000 vout_2000 vout_4000
vout_8000` overlays the four RC step responses immediately. The summary `sweep`
plot (the transfer curve) is still built exactly as before.

## Correctness

The demo is an RC low-pass (C = 1 nF) driven by a 1 V step, sweeping R so the
time constant RC scales 1/2/4/8 µs. Each overlaid curve is the exact step
response

```
v(out) = 1 - exp(-t/RC)
```

`verify_sweepwave.py` compares every resampled sample of every curve against
this closed form and finds the **worst error < 1e-4** — the resampling is
faithful, not just visually close. The interpolation is piecewise-linear on the
merged grid, so it never overshoots the endpoints of a run.

## Graceful when there's no waveform

If the inner analysis produces a scalar (an `op`), there is nothing to overlay:
`-overlay` prints `-overlay ignored (analysis '…' has no waveform to overlay)`
and the ordinary summary curve is produced. It is never an error.

## Verification

`verify_sweepwave.py` — 5 checks: the `sweepwave` plot is built and the
resampled family matches `1-exp(-t/RC)` to < 1e-4; each knob value gets a
distinct `<out>_<val>` vector; `-overlay` is ignored gracefully on a scalar
`op`; and the E-146 summary last-value curve is still recorded correctly (shared
recording path). It is a front-end command, independent of the linear solver, so
it runs once.

## Running

```sh
python3 verify_sweepwave.py
ngspice -b sweepwave_demo.cir
```
