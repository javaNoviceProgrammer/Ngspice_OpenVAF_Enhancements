# Enhancement-299 — ngspice: pyplot cross-run overlay, cursor, and data export

The finishing touches on `pyplot`: robust overlay of several runs, an interactive crosshair,
and a note on what is already there for data export.

## Cross-run overlay of different-length runs

ngspice already overlays results from different runs through its `plotname.vector` reference
syntax:

```
tran 5u 3m           $ -> plot tran1
alter c1 c=400n
tran 5u 3m           $ -> plot tran2
pyplot cmp tran1.v(out) tran2.v(out)
```

That worked, but the data table was sized by the **first** vector's scale, so overlaying a
longer second run silently **truncated** it. The table is now sized by the **longest** scale
across the plotted vectors; each vector still uses its own scale for x, and shorter ones pad
with NaN (which matplotlib skips). A single run is unchanged (all vectors share one scale).

## Interactive crosshair — `pyplot_cursor`

```
set pyplot_cursor
pyplot v(out)
```

adds a crosshair that follows the mouse, using matplotlib's built-in `Cursor` widget — **no
extra Python package**. It is interactive-only: it is not emitted for a hardcopy, where there
is no mouse. Pan, zoom and save-image are already provided by matplotlib's own window
toolbar, so they need nothing added.

## Data export — already there

Every `pyplot` writes `<name>.data` (the plotted columns) beside `<name>.py`. That file *is*
the export — load it anywhere:

```python
import numpy as np
d = np.loadtxt("fig.data")
```

and `<name>.py` is a self-contained, editable matplotlib script.

## Verification

`examples/pyplotmore_examples/verify_pyplotmore.py` — a two-run overlay whose second run is
finer keeps **every** sample of both traces (before, the finer run was cut to the first
run's length); `pyplot_cursor` is confirmed present in a window script and **absent** from a
hardcopy script.

## Scope

`src/frontend/plotting/pyplot.c`. No other command affected.
