# Enhancement-94 — the `pyplot` command (matplotlib backend)

Enhancement-94 adds a new ngspice interactive command, **`pyplot`**, that
renders simulated vectors with **matplotlib** — a Python counterpart to the
existing `gnuplot` command.

## Usage

```
pyplot <file> <plot expressions...>
```

Like `gnuplot`, the first word is the output file base name and the rest are
ordinary plot expressions (the same syntax `plot` accepts). `pyplot` writes a
`<file>.data` table and a `<file>.py` matplotlib script and runs Python on it:

```spice
.control
run
pyplot rc v(out) v(in)          ; opens an interactive matplotlib window
.endc
```

Two `set` variables control it:

- **`pyplot_terminal=png`** — render headless (matplotlib's `Agg` backend) to
  `<file>.png` instead of opening a window. Ideal for batch/`-b` runs and CI.
- **`pyplot_python=<interp>`** — the Python interpreter to run (default
  `python3`).

The generated script honours the current plot's title, axis labels, log
scales (`ac`/`loglog` etc. → `set_xscale('log')`), grid, axis limits, a legend,
and the marker/step style implied by `plot`'s point/comb modes.

## Implementation

Modelled directly on the gnuplot backend:

- **`src/frontend/plotting/pyplot.c`** — `ft_pyplot()` writes the data table
  (an `(x, y)` column pair per vector, real part for complex data) and emits
  the matplotlib script, then `system()`s `python3 <file>.py` (synchronously
  for a PNG, in the background for an interactive window). It mirrors
  `ft_gnuplot()`'s structure and reuses the same `plotit()` vector-expression
  machinery.
- **`src/frontend/plotting/plotit.c`** — a new `"pyplot"` device arm alongside
  `"gnuplot"`/`"writesimple"`.
- **`src/frontend/com_pyplot.c`** — the `com_pyplot()` command wrapper (mirrors
  `com_gnuplot()`).
- **`src/frontend/commands.c`** — `pyplot` registered in both command tables.
- Makefiles updated for the two new source files.

Because `pyplot` goes through `plotit()`, it accepts the full range of plot
expressions, vector arithmetic, and ranges that `plot`/`gnuplot` do.

## Verification

`pyplot_examples` (6/6): an OpenVAF/OSDI model (`rcload.va`) is simulated and

- a transient `pyplot rc v(out) v(in)` writes `rc.py`, `rc.data` and a valid
  `rc.png` (checked by PNG magic bytes and size); the generated script is
  confirmed to load matplotlib and plot both vectors;
- an AC sweep `pyplot acmag db(v(out))` renders a log-x-axis PNG.

Full regression: 86 verify suites + 28 integration tests. `pyplot` is purely
additive (a new command + backend); nothing else changed. matplotlib must be
installed for the Python side (as gnuplot must be for `gnuplot`).
