# Enhancement-95 — optional file name for `pyplot`

A small refinement to Enhancement-94's `pyplot` command: the output file base
name is now **optional**, so you can plot directly without inventing a name.

## Before / after

Enhancement-94 required the base name as the first argument (like `gnuplot`),
so `pyplot v(out)` silently did nothing — the single word `v(out)` was taken
as the file name, leaving no plot arguments. Now:

```spice
pyplot v(out) v(in)      ; no file name -> writes pyplot.py / pyplot.png
pyplot out in            ; bare node names -> also defaults to "pyplot"
pyplot myplot v(out)     ; an explicit base name still works -> myplot.png
```

## How the first word is classified

`com_pyplot()` treats the first word as a file name **only if it is not itself
a plot expression** — that is, it contains no `(` (as in `v(out)`, `db(...)`)
and does not name an existing vector (as a bare node name like `out` would,
checked with ngspice's `vec_get()`). Otherwise the base name defaults to
`pyplot` and every word is a plot argument.

This resolves the common cases unambiguously: a leading `v(...)`/`i(...)`
expression or a bare node name defaults the name; a plain word that is not a
vector is used as the name. Two supporting fixes: the command's minimum
argument count was lowered from 2 to 1 (so a single-vector `pyplot v(out)`
reaches the handler), and the help text is now `[file] plotargs`.

## Verification

`pyplot_examples` (7/7): the Enhancement-94 checks plus a new one confirming
`pyplot v(out)` with no file name renders the default `pyplot.png`. Full
regression: 86 verify suites + 28 integration tests. ngspice-only and additive.
