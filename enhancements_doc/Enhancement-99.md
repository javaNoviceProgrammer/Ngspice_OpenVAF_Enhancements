# Enhancement-99 — `pyplot` vector export formats (SVG/PDF) and figure size (version11)

Two more additions to the Enhancement-94/95/98 `pyplot` command: **vector
export formats** (SVG and PDF alongside the existing PNG) and a **figure size**
control, both driven by `set` variables.

## `set pyplot_terminal=svg|pdf` — vector output

Enhancement-94 added `set pyplot_terminal=png` for headless (matplotlib Agg)
rendering to `<file>.png`. Enhancement-99 extends the same mechanism to the two
vector formats matplotlib writes natively:

```spice
set pyplot_terminal=svg
pyplot out v(in) v(out)       ; writes out.svg

set pyplot_terminal=pdf
pyplot out v(in) v(out)       ; writes out.pdf
```

Any of `png`, `svg`, `pdf` (or the `.../quit` spellings) selects headless
rendering; the file extension follows the format. Without `pyplot_terminal`,
`pyplot` still opens an interactive matplotlib window as before.

## `set pyplot_figsize="W,H"` — figure size

`pyplot_figsize` sets the figure size in inches, passed straight to
matplotlib's `plt.subplots(..., figsize=(W, H))`:

```spice
set pyplot_terminal=svg
set pyplot_figsize="8,3"
pyplot out v(in) v(out)       ; an 8x3-inch out.svg
```

> **Quote the value.** ngspice's `set` truncates an unquoted value at the first
> comma (`set pyplot_figsize=8,3` stores just `8`), so the pair must be quoted:
> `set pyplot_figsize="8,3"`. A space or `x` separator is also accepted inside
> the quotes (`"8 3"`, `"8x3"`). An unparseable or non-positive value is
> ignored and matplotlib's default size is used.

The figure size applies to the single-axis and the Enhancement-98 multi-panel
(`pyplot_subplots`) layouts alike.

## Implementation

All in `ft_pyplot()` (`src/frontend/plotting/pyplot.c`):

- `pyplot_terminal` is parsed into a format string `fmt` (`png`/`svg`/`pdf`)
  and a `hardcopy` flag; `hardcopy` gates the `matplotlib.use('Agg')` import,
  the `fig.savefig(<file> + '.<fmt>', dpi=100)` call (matplotlib picks the
  writer from the extension), and the synchronous (non-backgrounded) run;
- `pyplot_figsize` is read with `sscanf(..., "%lf%*[ ,xX]%lf", &figw, &figh)`;
  when two positive values parse, the `plt.subplots(...)` call gains a
  `figsize=(figw, figh)` argument.

## Verification

`pyplotexport_examples` (5/5): an RC transient rendered with
`pyplot_terminal=svg` + `pyplot_figsize="8,3"`, `pyplot_terminal=pdf`, and
`pyplot_terminal=png` — the outputs are checked by magic bytes (`<?xml`,
`%PDF`, `\x89PNG`), and the generated scripts are checked for `figsize=(8, 3)`
when set and no `figsize=` when unset. Full regression: 90 verify suites + 28
integration tests. Purely additive.
