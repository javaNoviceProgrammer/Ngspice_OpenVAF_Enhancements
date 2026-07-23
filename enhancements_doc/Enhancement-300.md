# Enhancement-300 — ngspice: `pyplot_mplcursors` backend for the interactive cursor

Enhancement-299 added `set pyplot_cursor`, a hover crosshair drawn with matplotlib's
built-in `Cursor` widget. This adds an alternative backend for users who have the
[`mplcursors`](https://mplcursors.readthedocs.io/) package installed — **data cursors** that
snap to a trace and show its `(x, y)` value on hover, rather than a plain crosshair.

```
set pyplot_mplcursors
pyplot v(out)
```

## Behaviour

* `set pyplot_mplcursors` selects the mplcursors backend **and turns the cursor on**, so it
  works on its own (no need to also set `pyplot_cursor`).
* With `pyplot_mplcursors` **unset**, the cursor — when enabled by `pyplot_cursor` — uses the
  default `matplotlib.widgets.Cursor` crosshair, exactly as before.
* Interactive-only: like `pyplot_cursor`, it is not emitted for a hardcopy
  (`pyplot_terminal=png/svg/pdf`), where there is no mouse.

The generated script imports `mplcursors` inside a `try`, and **falls back to the built-in
`Cursor`** if the package is not importable where the script runs — so a deck written on a
machine that has mplcursors still works on one that does not.

```python
try:
    import mplcursors
    _mpl = mplcursors.cursor(hover=True)
except Exception:
    from matplotlib.widgets import Cursor
    _curs = [Cursor(_a, useblit=True, color='0.5', linewidth=0.8) for _a in axes[:, 0]]
```

`mplcursors` lives in the emitted Python, not in ngspice — so it is the interpreter named by
`pyplot_python` that must have the package. Point ngspice at that interpreter if it is not
the default:

```
set pyplot_python=python3.13
set pyplot_mplcursors
pyplot v(out)
```

## Verification

`examples/pyplotmore_examples/verify_pyplotmore.py` — `pyplot_mplcursors` on its own emits
the `mplcursors.cursor(hover=True)` branch with the built-in-`Cursor` fallback; `pyplot_cursor`
alone still emits the built-in `Cursor` and no mplcursors; neither appears in a hardcopy.
The mplcursors branch was additionally executed under an interpreter that has the package
(confirmed to call `mplcursors.cursor(hover=True)`), and the fallback under one that does not
(degrades to `Cursor` with no error).

## Scope

`src/frontend/plotting/pyplot.c`. No other command affected; the default cursor behaviour
(Enhancement-299) is unchanged when `pyplot_mplcursors` is unset.
