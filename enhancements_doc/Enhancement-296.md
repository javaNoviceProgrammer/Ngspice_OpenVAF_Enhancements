# Enhancement-296 — ngspice: pyplot appearance controls

Seven new `set` variables give finer control over a `pyplot` figure without editing the
generated Python. All are additive: with none set, the output is byte-for-byte what it was.

| Variable | Effect | Default |
|---|---|---|
| `pyplot_grid` | `on` / `off` / `x` / `y` — override the default (grid follows axis type) | axis-dependent |
| `pyplot_legend` | `off` hides it; any other value is the matplotlib location (`upper_right`, `best`, …) | `legend()` |
| `pyplot_markers` | a marker at each sample **on top of** the line, cycling shape per trace | lines only |
| `pyplot_axhline` | comma list of y values → horizontal reference lines | none |
| `pyplot_axvline` | comma list of x values → vertical reference lines | none |
| `pyplot_dpi` | savefig resolution | 100 |
| `pyplot_transparent` | transparent figure background for a hardcopy | opaque |

```
set pyplot_terminal=png
set pyplot_markers
set pyplot_grid=off
set pyplot_legend=upper_right
set pyplot_axhline=0.5,-0.5
set pyplot_axvline=1m,2m
set pyplot_dpi=150
set pyplot_transparent
pyplot fig v(in) v(out)
```

## Details worth knowing

* **`pyplot_legend` and multi-word locations.** ngspice's `set` keeps only the first word,
  so `set pyplot_legend=upper right` would capture just `upper`. Use the underscore form
  (`upper_right`); the renderer converts it back to a space.
* **`pyplot_axhline` / `pyplot_axvline`** accept SI suffixes (`1k`, `0.5n`) via ngspice's
  own numeric parser, so a vertical line at 1 kHz is `pyplot_axvline=1k`.
* **`pyplot_markers` vs `pointstyle=markers`.** The existing `pointstyle=markers` draws
  markers with **no** line; `pyplot_markers` keeps the line and adds a cycling marker
  (`o s ^ D v * P X`) so overlaid traces are distinguishable in print or greyscale.

## Verification

`examples/pyplotmore_examples/verify_pyplotmore.py` — each control is checked to appear in
the emitted script, the script is executed (matplotlib Agg) so a broken emission fails, and
a control-free `pyplot` is confirmed byte-identical to the old default path.

## Scope

`src/frontend/plotting/pyplot.c`. No other command affected.
