% The ngspice `pyplot` command — feature package
% ngspice-46 + OpenVAF-r enhancement project

## What the feature is

`pyplot` is an ngspice interactive/`.control` command that plots simulation
vectors with **matplotlib** — the same role `gnuplot` plays, but rendering
through Python/matplotlib. It writes a self-contained `<name>.data` table and a
`<name>.py` matplotlib script and then runs Python on the script, either
opening an interactive window or, with a file terminal, rendering a headless
image (PNG/SVG/PDF).

```
pyplot [file] <vectors|expressions> [title '...'] [xlabel ...] [ylabel ...]
       [xlimit lo hi] [ylimit lo hi]
```

The output **file name is optional**; a bare net name plots its node voltage
(no `v()` needed), and every plot argument may be an expression (`v(out)`,
`db(v(out))`, `out1+6`, …).

### Options (`set` variables)

| `set` variable            | effect |
|---------------------------|--------|
| `pyplot_terminal=png\|svg\|pdf` | render headless to `<name>.<fmt>` instead of a window |
| `pyplot_subplots=N`       | N traces per stacked subplot (shared x-axis); 0/unset = one axis |
| `pyplot_style=<name>`     | a matplotlib style sheet (`dark`, `ggplot`, `bmh`, …) |
| `pyplot_figsize=W,H`      | figure size in inches |
| `pyplot_python=<exe>`     | the Python interpreter (default `python3`) |
| `pyplot_linewidth=<w>`    | line width in points for every trace *(Enhancement-183)* |
| `pyplot_backend=<name>`   | matplotlib backend, e.g. `TkAgg`/`QtAgg`/`MacOSX`/`Agg` *(Enhancement-183)* |
| `pointstyle=markers`      | draw points instead of lines |

Example:

```
.control
run
set pyplot_terminal=png
set pyplot_linewidth=2.0
set pyplot_subplots=1
pyplot chain Vin out1 out2 out3 title 'inverter chain'
.endc
```

## Files changed

Baseline = the pristine `original/ngspice-46` tree; the feature lives entirely
in the `pyplot` command front-end. `windisp.c` also matches a grep for
"pyplot" but its 16 mentions are **pre-existing in the baseline** (an unrelated
Windows-display symbol) — it is *not* part of this feature and is not shipped.

| File | Kind | Lines | Role |
|------|------|-------|------|
| `src/frontend/com_pyplot.c` | **new** | 94 | the `pyplot` command: file-name/dir handling, dispatch |
| `src/frontend/com_pyplot.h` | **new** | 5  | its prototype |
| `src/frontend/plotting/pyplot.c` | **new** | 329 | `ft_pyplot()` — writes the `.data` table + `.py` script and runs Python |
| `src/frontend/plotting/pyplot.h` | **new** | 15 | `ft_pyplot()` prototype |
| `src/frontend/commands.c` | modified | — | registers `pyplot` in the command tables (`spcp_coms`, `nutcp_coms`) |
| `src/frontend/plotting/plotit.c` | modified | — | routes `devname == "pyplot"` to `ft_pyplot()`, passing user x/y limits only when given |
| `src/frontend/Makefile.am` | modified | — | adds `com_pyplot.{c,h}` to the build |
| `src/frontend/plotting/Makefile.am` | modified | — | adds `pyplot.{c,h}` to the build |

`Makefile.in` is generated from `Makefile.am` by `autogen.sh`/autoconf — only
the `.am` files are shipped; regenerate the `.in` with the project's bootstrap.

### The feature's lines in the shared (modified) files

`commands.c` — command registration (two dispatch tables):

```c
#include "com_pyplot.h"
...
{ "pyplot", com_pyplot, FALSE, TRUE,
  "pyplot [file] plotargs : plot vectors with matplotlib" },
```

`plotit.c` — the dispatch to the pyplot back-end (only pins the axes for
explicit user limits, otherwise leaves matplotlib to autoscale):

```c
#include "pyplot.h"
...
if (devname && eq(devname, "pyplot")) {
    ft_pyplot(user_xlim ? xlims : NULL, user_ylim ? ylims : NULL,
              xdelta, ydelta, filename, title, xlabel, ylabel,
              gridtype, plottype, vecs);
    ...
}
```

## Enhancement history

`pyplot` was built incrementally; each enhancement is documented in
`enhancements_doc/`:

| Enhancement | What it added |
|-------------|---------------|
| **E-94**  | the `pyplot` command + PNG output (matplotlib back-end) |
| **E-95**  | optional output file name (defaults to `pyplot`) |
| **E-98**  | `pyplot_subplots`, `pyplot_style`, marker/point styles |
| **E-99**  | SVG/PDF terminals + `pyplot_figsize` |
| **E-182** | autoscale by default (`fig.tight_layout()`); pin axes only for explicit `xlimit`/`ylimit` |
| **E-183** | distinct default names for successive no-name plots; write `.py`/`.data`/`.png` next to the `.cir`; `pyplot_linewidth`; `pyplot_backend` |

### Enhancement-183 (this package's newest changes)

1. **Distinct default names** — in window mode the Python viewer is launched in
   the background, so two plots that both omit the file name raced on the same
   `pyplot.py`/`pyplot.data` and both windows showed the *second* plot. Later
   no-name plots are now `pyplot-2`, `pyplot-3`, … (first stays `pyplot`).
2. **Deck-folder output** — the `.py`/`.data`/`.png` are written next to the
   circuit file (via `ngdirname(ci_filename)`), not ngspice's cwd; the script's
   `loadtxt`/`savefig` carry the full path. A bare in-folder deck name is
   unchanged (cwd).
3. **`pyplot_linewidth=<w>`** — line width for every trace.
4. **`pyplot_backend=<name>`** — explicit matplotlib backend (`matplotlib.use`),
   overriding the automatic choice.

## How it works

1. `com_pyplot()` peels an optional leading file name (a word that is not itself
   a plot expression / vector), defaults it to `pyplot` (uniquified per session),
   and — for a bare name — prefixes the circuit file's directory. It then calls
   the shared `plotit()` with device `"pyplot"`.
2. `plotit()` parses the vector expressions and, recognizing the `pyplot`
   device, calls `ft_pyplot()`.
3. `ft_pyplot()` writes the numeric data to `<name>.data`, emits a matplotlib
   script `<name>.py` (backend/style/figsize/subplots/linewidth honored, title
   and labels quoted, axes autoscaled unless the user gave limits), and runs
   `python3 <name>.py` — synchronously for a file terminal, in the background
   for an interactive window.

## Verification

`examples/pyplot_examples/verify_pyplot.py` — 13 checks under **both** ngspice
linear solvers: the OSDI-model transient renders a valid PNG whose script plots
the requested vectors; autoscale vs explicit-limit behavior; an AC log-scale
plot; the optional-file-name default; and the four Enhancement-183 behaviors
(distinct default names with correct titles, deck-folder output, `linewidth`,
`backend`).

## Archive contents

```
pyplot_feature_report.md                       this report
pyplot_feature_report.pdf                       PDF rendering
ngspice-46/src/frontend/com_pyplot.c            (new)
ngspice-46/src/frontend/com_pyplot.h            (new)
ngspice-46/src/frontend/plotting/pyplot.c       (new)
ngspice-46/src/frontend/plotting/pyplot.h       (new)
ngspice-46/src/frontend/commands.c              (modified — carries other commands too)
ngspice-46/src/frontend/plotting/plotit.c       (modified — carries other plotting too)
ngspice-46/src/frontend/Makefile.am             (modified)
ngspice-46/src/frontend/plotting/Makefile.am    (modified)
examples/pyplot_examples/                        the verifying example suite
```
