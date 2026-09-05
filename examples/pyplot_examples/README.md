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

Run: `python3 verify_pyplot.py` (24 checks, both solvers).
