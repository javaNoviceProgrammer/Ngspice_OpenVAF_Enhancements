# CSV output for `wrdata` (Enhancement-231)

ngspice's `wrdata` writes **whitespace-separated** columns, with every vector
prefixed by its own scale column. The available knobs (`wr_singlescale`,
`wr_vecnames`, `wr_onespace`, `numdgt`) never produced a real comma-separated
file, so exporting to a spreadsheet or `pandas`/`csv` reader meant a
post-processing step. This enhancement gives `wrdata` a first-class CSV mode.

## Usage

Two equivalent ways — a sticky option and a per-call flag:

```
* option form
set wr_csv
wrdata out.csv v(out) i(v1)
unset wr_csv

* flag form (any position; enables CSV for just this write)
wrdata -csv out.csv v(out) i(v1)
wrdata out.csv v(out) i(v1) -csv
```

CSV mode writes:

* a **header row** of names (implies `wr_vecnames`),
* a **single shared scale column** — `time`, `frequency`, … — written once
  (implies `wr_singlescale`, so all vectors must share one scale length), and
* **comma-separated** values with no leading/trailing padding.

```
time,v(in),v(out)
0.00000000e+00,0.00000000e+00,0.00000000e+00
1.00000000e-09,1.00000000e-03,9.99000999e-07
...
```

For `.ac`, each complex vector becomes **two columns** (real, imaginary) under
its name. Precision follows `set numdgt` (default 8 significant digits).

The `-csv` flag is a per-call alias for `set wr_csv`: it enables CSV for that
one write and restores the prior global state afterward, so it never leaks into
later `wrdata` calls. Default (no-CSV) output is byte-for-byte unchanged.

## Verify

```sh
python3 verify_csv.py
```

Checks that default output is unmodified; that `set wr_csv` and `wrdata -csv`
(in first / middle / last argument positions) produce identical, header-topped,
comma-separated files; that the numbers match the default format bit-for-bit;
that `.ac` emits real/imag columns and `.tran` a `time` scale; and that the flag
does not leak into the following plain `wrdata`.
