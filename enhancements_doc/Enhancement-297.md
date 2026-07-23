# Enhancement-297 — ngspice: `pyplot -fft` magnitude spectrum

`pyplot [name] -fft <sig> [sig ...]` plots the one-sided amplitude spectrum of each signal —
turning a multi-step ritual (`fft`/`spec`, then plot) into one command, in the spirit of
`-eye`.

```
tran 5u 20m
let sig = ...
pyplot spectrum -fft sig
```

## Why it resamples first

Transient data is **adaptively sampled** — the timestep varies. A raw `rfft` over
non-uniform samples would be wrong, so the generated script resamples each signal onto a
uniform grid (`np.interp`) before the transform. Everything is done in the emitted Python
with numpy alone (no new ngspice machinery, no extra Python package).

The one-sided magnitude is scaled by `2 / sum(window)`, so a pure tone reads back **its
amplitude** at its frequency.

| Variable | Effect | Default |
|---|---|---|
| `pyplot_fft_window` | `hann` / `hamming` / `blackman` / `rect` | `hann` |
| `pyplot_fft_db` | plot `20·log10` magnitude | linear |
| `pyplot_fft_points` | resample / FFT length | next power of two ≥ len |
| `pyplot_fft_logf` | log frequency axis (drops the DC bin) | linear |

```
set pyplot_fft_window=blackman
set pyplot_fft_db
set pyplot_fft_logf
pyplot spectrum -fft sig
```

**Note on the log axis.** Use `pyplot_fft_logf`, not the command's `xlog`: `xlog` makes
ngspice validate the *time* scale (which includes t = 0) and abort before the FFT runs.
`pyplot_fft_logf` sets the log axis on the frequency data in Python and drops the DC bin so
`log(0)` is never plotted.

## Verification

`examples/pyplotmore_examples/verify_pyplotmore.py` — a synthesized
`2.0·sin(2π·1kHz·t) + 0.5·sin(2π·3kHz·t)` reads back **2.0 at 1 kHz and 0.5 at 3 kHz** to
better than 2% (a closed-form amplitude oracle, not a comparison to the old binary). The
window / dB / points / logf options are each confirmed in the emitted script, which is then
executed.

## Scope

`src/frontend/plotting/pyplot.c` (the `ft_pyplot` mode, now `LINE` / `HIST` / `FFT`),
`plotit.c` (dispatch), `com_pyplot.c` (the `-fft` marker). No other command affected.
