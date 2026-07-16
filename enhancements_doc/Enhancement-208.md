# Enhancement-208 — `pyplot -eye`: one-line matplotlib eye diagrams

A convenience bridge between the [`eye`](Enhancement-207.md) analysis and the
[`pyplot`](Enhancement-94.md) matplotlib back-end: `pyplot -eye <expr> -ui <T>`
runs the eye analysis **and** renders the result as a proper
persistence-style eye diagram in a single command — no manual `eye` → `wrdata`
→ external plotting script round-trip.

## Command

```
pyplot [name] -eye <expr> -ui <T> [-tstart t0] [-threshold vth] [-window frac]
```

The tokens after `-eye` are exactly the [`eye`](Enhancement-207.md) command's own
arguments (the expression and its flags). A single bare token *before* `-eye` is
taken as the output base name (`pyplot rxeye -eye v(rx) -ui 0.5n`); omitted, the
base name defaults to `eye`.

```
pyplot -eye v(rx) -ui 0.5n -tstart 3n        -> eye.png (or an interactive window)
pyplot rxeye -eye v(rx) -ui 0.5n             -> rxeye.png
```

## What it renders

`plot eye_wave vs eye_t` (the raw way to see the E-207 folded eye) draws a single
connected line through the folded samples in file order — a scribble, not an eye.
`pyplot -eye` instead draws the samples as a **2-D histogram** (`hist2d`, log-scaled
`LogNorm`, `turbo` colormap, empty cells masked): overlapping traces accumulate into
a persistence eye, exactly how a sampling scope paints one. It is annotated with the
metrics the `eye` command reports:

- the **decision threshold** (dashed) and the **eye centre** / sampling instant at
  1 UI (dotted) after folding;
- a vertical **eye-height** double-arrow at the eye centre;
- a horizontal **eye-width** double-arrow along the threshold;
- a title carrying UI, eye height, eye width (as a % of UI), and RMS jitter.

## Implementation

`com_pyplot()` detects the `-eye` marker, runs `com_eye()` on the trailing tokens
(which folds the waveform and leaves `eye_wave`/`eye_t` plus the scalar metrics in a
fresh current `eye` plot), then calls the new **`ft_pyplot_eye()`** in
`plotting/pyplot.c`. That function reads the folded vectors and metrics back from the
current plot, writes `<name>.data` (the folded sample pairs) and a `<name>.py`
matplotlib script, and launches Python with the *same* mechanism as `ft_pyplot()` —
so it honours every existing `pyplot_*` setting:

- `set pyplot_terminal=png|svg|pdf` → headless (Agg) hardcopy, run synchronously;
  otherwise an interactive window launched in the background;
- `set pyplot_python=<interp>`, `set pyplot_backend=<name>`,
  `set pyplot_figsize=W,H`, and `set pyplot_style=<sheet>` (a `dark` sheet flips the
  annotation colours to stay legible on a dark ground).

No numerical-core changes; the eye math is entirely E-207's. `ft_pyplot()` and the
gnuplot / asciiplot back-ends are untouched.

## Verification

[`examples/pyplot_examples/verify_pyplot.py`](../examples/pyplot_examples/verify_pyplot.py)
gains four checks (17 total × both solvers). A self-contained data eye — a
pseudo-random NRZ bit stream (PWL) through a bandwidth-limiting RC channel
(τ ≈ 0.5 UI) — is rendered with `pyplot eyefig -eye v(rx) -ui 0.5n`: the eye analysis
runs and reports its metrics, `eyefig.png` is a valid PNG, the generated script is a
`hist2d` persistence eye referencing the metrics, and the no-name form defaults the
base to `eye.png`. Full example regression: 170/170 (E-208 extends the existing
`pyplot_examples` suite rather than adding a folder, so the suite count is unchanged).

## Scope

Front-end only; solver-independent, like both parents. A convenience wrapper — it
adds no new measurement, it packages the E-207 eye + the E-94 matplotlib bridge into
one command so the classic eye diagram is a single line.
