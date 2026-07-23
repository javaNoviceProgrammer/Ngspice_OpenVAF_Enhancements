# Enhancement-298 — ngspice: `pyplot -bode` / `-nyquist` / `-polar` (complex-aware AC)

An ordinary `pyplot v(out)` on AC data silently keeps only the **real part** of the complex
result. At the −3 dB point of an RC low-pass it shows 0.5, not the magnitude 0.7071 — not
wrong (it is the SPICE convention, and `mag()`/`db()`/`ph()` are the explicit escapes), but
a surprise, and it makes the most common RF plot need manual conversion every time.

Three new modes use the **full complex value** instead:

```
ac dec 30 10 1e6
pyplot resp -bode    v(out)     $ magnitude(dB) / phase(deg) vs log-frequency, stacked
pyplot resp -nyquist v(out)     $ imag vs real
pyplot resp -polar   v(out)     $ magnitude at phase, polar projection
```

| Mode | View |
|---|---|
| `-bode` | two stacked panels — `20·log10|H|` (dB) and unwrapped phase (deg) — vs a log frequency axis |
| `-nyquist` | `imag(H)` vs `real(H)`, equal aspect, with the real/imag axes marked |
| `-polar` | `|H|` at `angle(H)` on a matplotlib polar projection |

Each accepts several signals (overlaid), honours the shared `pyplot_*` settings
(`pyplot_terminal`, `pyplot_backend`, `pyplot_style`, `pyplot_figsize`), and auto-names
successive default plots (`bode`, `bode-2`, …) through the same per-session counter as the
other modes.

## Implementation

`ft_pyplot_ac` emits one `<vec-index> <freq> <re> <im>` row per point — the imaginary part
is carried, not discarded — grouped by the first column so variable-length or multiple
vectors stay separate. The renderer reuses the file/launch scaffolding shared by the other
pyplot modes. `-bode` uses `np.unwrap` so the phase is continuous across ±180°.

## Verification

`examples/pyplotmore_examples/verify_pyplotmore.py` — for an RC low-pass at fc the Bode data
gives **−3.010 dB and −45.00°** (the exact first-order values, from the preserved complex
data), and all three modes' emitted scripts are executed under matplotlib Agg.

## Scope

`src/frontend/plotting/pyplot.c` (new `ft_pyplot_ac`), `plotit.c` (dispatch),
`com_pyplot.c` (the three markers). No other command affected.
