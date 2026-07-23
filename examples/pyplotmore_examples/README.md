# pyplotmore_examples — Enhancements 296-301

Four groups of additions to the `pyplot` command, all verified against closed-form
oracles where a number is involved (not just against the old binary).

| # | Adds | Verified by |
|---|---|---|
| 296 | Appearance controls: `pyplot_grid`, `pyplot_legend`, `pyplot_markers`, `pyplot_axhline`, `pyplot_axvline`, `pyplot_dpi`, `pyplot_transparent` | each control appears in the emitted script, the script runs, and the default path is unchanged |
| 297 | `-fft` — one-sided amplitude spectrum, with `pyplot_fft_window` / `_db` / `_points` / `_logf` | a `2.0 @ 1 kHz + 0.5 @ 3 kHz` tone reads back **its amplitude** (rel < 2%) |
| 298 | `-bode` / `-nyquist` / `-polar` — complex-aware AC views | Bode keeps the imaginary part: **−3.01 dB / −45°** at fc of an RC low-pass |
| 299 | Overlay of different-length runs renders fully; `pyplot_cursor` crosshair; the `.data` file is the data export | overlay keeps every trace; cursor emitted only in a window |
| 300 | `pyplot_mplcursors` — the `mplcursors` backend (data cursors) instead of the built-in crosshair, with a graceful fallback | the mplcursors branch + fallback are emitted; the built-in Cursor is still the default |
| 301 | `pyplot_cursor` is the single master switch (off by default); `pyplot_mplcursors` only selects the backend | the full gating truth table |

## The point of 298

An ordinary `pyplot v(out)` on AC data silently keeps only the **real part** — at the
−3 dB point it shows 0.5, not the magnitude 0.7071. The three new modes use the full
complex value instead: `-bode` gives magnitude(dB)/phase(deg) vs log-frequency, `-nyquist`
plots imag vs real, `-polar` puts magnitude at phase on a polar projection.

## Verify

```bash
python3 verify_pyplotmore.py
```

Runs under both linear solvers and prints a combined verdict (26 checks). Every generated
matplotlib script is also executed (Agg), so a syntactically broken emission fails — not
only a missing keyword.
