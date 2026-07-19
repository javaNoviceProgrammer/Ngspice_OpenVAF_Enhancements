# Enhancement-231 — CSV output for `wrdata` (`set wr_csv` + `wrdata -csv`)

`wrdata` is ngspice's simple table writer, but it only ever produced
**whitespace-separated** columns. Getting a genuine comma-separated file — for a
spreadsheet, `pandas`, or any `csv` reader — meant a post-processing pass (strip
leading spaces, collapse runs to commas). The only `-csv` anywhere in ngspice
was `show -csv`, which dumps *device-parameter* tables for documentation, not
simulation results. This enhancement gives `wrdata` a first-class CSV mode.

## What `wrdata` wrote before

`com_write_simple` (`frontend/com_gnuplot.c`) hands off to
`plotit(…, "writesimple")`, which calls **`ft_writesimple`**
(`frontend/plotting/gnuplot.c`). Every field there is emitted with the format
`"% .*e "` — a fixed-width, space-separated column, with each vector preceded by
its own scale column. The existing knobs (`wr_singlescale`, `wr_vecnames`,
`wr_onespace`, `numdgt`) tune spacing and precision but never change the
separator. There was no comma path.

## The two mechanisms

**`set wr_csv`** — a boolean option, read in `ft_writesimple` alongside the
existing `wr_*` variables. When set it takes a dedicated, self-contained CSV
branch that:

- writes a **single shared scale column** once (implies `wr_singlescale`, so the
  existing equal-length sanity check applies and errors cleanly otherwise),
- writes a **header row** of vector names (implies `wr_vecnames`),
- emits **comma-separated** values with `"%.*e"` (no sign-padding, no trailing
  separator), honouring `numdgt` for precision.

Complex vectors (`.ac`) become two columns — real, imag — under the vector's
name. The branch writes and returns before the space-formatted code, so default
`wrdata` output is **byte-for-byte unchanged**.

**`wrdata -csv <file> <vec…>`** — a per-call alias for `set wr_csv`, accepted in
*any* argument position. `com_write_simple` scans the wordlist for a `-csv`
token, and if found enables `wr_csv` for just that write, restoring the prior
global state afterward (so the flag never leaks into a later `wrdata`).

Because `plotit` **copies** its wordlist before working on it (it never mutates
or frees the caller's list), the `-csv` node can be safely spliced out for the
duration of the call and **relinked afterward**, leaving the caller's original
wordlist intact to free. The head case is detected by comparing against the list
pointer directly (`csvnode == wl`) rather than `wl_prev`, since the incoming
head's `wl_prev` is not necessarily null. No-vector forms (`wrdata -csv`,
`wrdata -csv file`) fall through the same `if (wl)` guard and write nothing, with
the node still relinked.

## Verification (`examples/csv_examples`)

`verify_csv.py` (9 checks) confirms: default output is unmodified (no commas);
`set wr_csv` writes a header-topped, comma-separated file with the right values;
`wrdata -csv` in first / middle / last position is byte-identical to the option
form; the CSV numbers equal the default-format numbers bit-for-bit; the flag does
not leak into the following plain `wrdata`; `.ac` emits real/imag columns under a
`frequency` scale; and `.tran` emits a `time` scale with uniform, `csv`-parseable
rows.

## Scope

ngspice frontend only, two files (`frontend/com_gnuplot.c`,
`frontend/plotting/gnuplot.c`); no solver, analysis, device, or compiler change,
and default `wrdata` output is preserved exactly. Full regression: 190/190.
