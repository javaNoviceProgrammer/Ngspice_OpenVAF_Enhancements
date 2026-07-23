# Enhancement-301 — ngspice: `pyplot_cursor` is the single master switch for the interactive cursor

Enhancement-299 added the built-in `Cursor` crosshair and Enhancement-300 added the
`mplcursors` backend, but the two enable-switches had drifted: `pyplot_mplcursors` turned
the cursor on **by itself**, so there was no single knob that meant "cursor off". This
consolidates the gating so **`pyplot_cursor` is the one on/off switch** — off by default —
and `pyplot_mplcursors` only *selects the backend* when the cursor is on.

## The gating, after this change

| `pyplot_cursor` | `pyplot_mplcursors` | Result |
|---|---|---|
| unset | unset | **no cursor** (default) |
| unset | set | **no cursor** — mplcursors alone no longer enables it |
| set | unset | built-in `matplotlib.widgets.Cursor` crosshair |
| set | set | `mplcursors` data cursors (fallback to the built-in) |
| — | — | *always off in a hardcopy* (`pyplot_terminal=png/svg/pdf`) |

```
* the cursor is off unless you ask for it
pyplot v(out)                 $ no cursor

set pyplot_cursor
pyplot v(out)                 $ built-in crosshair

set pyplot_mplcursors
pyplot v(out)                 $ mplcursors (cursor is still on from above)
```

## What changed and why

The only functional change is the enable condition: it was
`pyplot_cursor OR pyplot_mplcursors`, and is now `pyplot_cursor` alone. This makes the
feature predictable — one variable to reason about — and matches every other optional
`pyplot` behaviour, which is off until explicitly set.

`pyplot_mplcursors` keeps its meaning: with the cursor on, it chooses the `mplcursors`
package (which must be importable by the interpreter named by `pyplot_python`), and the
emitted script still falls back to the built-in `Cursor` if that import fails.

## Verification

`examples/pyplotmore_examples/verify_pyplotmore.py` — the full gating truth table is
checked: default off, `pyplot_cursor` alone → built-in, `pyplot_mplcursors` **alone → off**,
both → mplcursors (with fallback), and off in a hardcopy. Full dual-solver regression
238/238 OK.

## Scope

`src/frontend/plotting/pyplot.c`, one condition. No other command affected.
