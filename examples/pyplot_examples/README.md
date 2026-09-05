# pyplot_examples — the `pyplot` command (matplotlib backend) (Enhancement-94)

A new ngspice command, `pyplot`, plots simulated vectors with **matplotlib** —
a Python counterpart to `gnuplot`. Same syntax: `pyplot <file> <expr...>`. With
`set pyplot_terminal=png` it renders headless (Agg) to `<file>.png`;
`set pyplot_python=<interp>` picks the interpreter (default `python3`).

`rcload.va` (a 1 kΩ OSDI conductance) is simulated; the verify runs a transient
`pyplot rc v(out) v(in)` and an AC `pyplot acmag db(v(out))`, then confirms the
generated matplotlib scripts render valid PNGs. Requires matplotlib installed.

**Enhancement-208 — `pyplot -eye`:** `pyplot [name] -eye <expr> -ui <T>` runs the
[`eye`](../eye_examples) analysis and renders the folded eye directly as a
persistence-style 2-D-histogram eye diagram (annotated with eye height / width /
jitter), honouring the same `pyplot_*` settings — the classic eye diagram in one
line. The verify drives a pseudo-random NRZ bit stream through a bandwidth-limiting
RC channel and checks the eye PNG renders.

**Enhancement-547 — the launch is quoted and its status is judged.** The
command line that runs the generated script used to be built unquoted, so with
the deck-folder output of E-183 a folder named `My Circuits` handed Python the
file `My` and an apostrophe left the shell waiting for a closing quote: the
script and data were written, no image was, and ngspice went on. And only a
`-1` from `system()` was ever looked at, so a missing interpreter or a missing
matplotlib printed Python's own complaint and nothing else — a batch deck
finished with exit status 0 and no figure. Now the interpreter and the script
path are quoted (`pyplot_python` still carries options such as
`/usr/bin/env python3`; a value that names an executable path with a space is
one word), a hardcopy's non-zero exit is named together with the image that
was not written, and **`pyplot_status`** holds the status for the deck, as
`shell` publishes `shellstatus`:

```
pyplot fig v(out)
if $pyplot_status ne 0
  echo no figure -- see the message above
  quit 1
end
```

A window is launched in the background, where nothing can be waited for; on
POSIX the background shell reports a non-zero exit when it happens.

**Enhancement-548 — the script and its data.** Four defects from the same
review. The data table is written with 17 significant digits instead of six: a
time axis offset to 1 s with 1 ns steps used to collapse to one distinct x, and
a microvolt ripple on 1 V to eight distinct values, in the very file the doc
calls the export. `ylimit lo hi` under `ylog` was dropped without a word; it is
applied now (a non-positive bound never reaches the backend: the command
refuses it with `Y values must be > 0 for log scale`). A voltage and a
current on one plot shared one axis with no label at all, the milliamps flat
along the bottom of the volt scale; each type now has its own scale, the first
trace's type on the left and any other on a `twinx()` on the right, labelled
`V` and `A`, one combined legend, explicit colours (a twin axis restarts the
colour cycle). And the generated script found its data relative to the
directory ngspice ran in, so re-running it elsewhere failed with
`NAME.data not found`; it now resolves its data table and its image against
its own location.

**Enhancement-549 — the data table is `.npy`, and `-export` writes just that.**
The table every `pyplot` writes beside its script is now numpy's own array
file, `<name>.npy`: a *structured* array with one named field per column
(`time`, `v(out)`, `time_2`, `v(in)`), exact doubles, a fraction of the text
size, loaded in milliseconds — `np.load('sig.npy')['v(out)']` is the signal
and `pandas.DataFrame(np.load(...))` a table. `set pyplot_export=ascii`
restores the whitespace `.data` text, now with a `# name ...` header line and
17-digit numbers; the generated script loads whichever was written. And
`pyplot -export [name] v(out) i(v1)` writes the table and nothing else (no
script, no Python), with the same expressions, `vs` and plot-qualified names a
plot takes; it refuses the other markers, whose tables are written beside
their plots anyway. The written header follows numpy's format 1.0 exactly
(magic, version, little-endian length, 64-byte-aligned dict, raw doubles in
the host's byte order declared in the dtype).

Run: `python3 verify_pyplot.py` (35 checks, both solvers).
