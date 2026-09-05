# Enhancement-549: `pyplot` writes its data table as `.npy`, `set pyplot_export=bin|ascii`, and `pyplot -export` writes just the table

**Scope:** improvement 1 of the `pyplot` review recorded in
[E-547](Enhancement-547.md). **ngspice only; the compiler is unchanged.**

**Suites:** [`pyplot_examples`](../examples/pyplot_examples/) 29 → 35; the
four suites that parse the table (`pyplotcontour`, `pyplotsmith`,
`pyplotmore`, `pyplothist`) read either format; the twelve suites that
exercise pyplot pass. Reference
[§12.3–12.4](../docs/internals/ngspice_internals/ngspice_pyplot.md).

## What changed

* **`.npy` by default.** The five renderers write through one table writer.
  The default file is `<name>.npy`, numpy's own array format written straight
  from C — format 1.0: the magic, the version, a little-endian header length,
  a 64-byte-aligned header, raw doubles in the host's byte order declared in
  the dtype. It is a **structured** array with one named field per column
  (`time`, `v(out)`, `time_2`, `v(in)`; a repeated name numbered), so
  `np.load('sig.npy')['v(out)']` is the signal and
  `pandas.DataFrame(np.load(...))` a table. The contour, Smith, AC and eye
  tables carry their own field names.
* **`set pyplot_export=ascii`** (also `text`, `txt`, `data`) restores the
  whitespace `.data` table, which now carries a `# time v(out) …` header line
  that `np.loadtxt` skips and 17-digit numbers; `bin`, `npy` and `binary`
  select the default; an unknown value is reported and treated as `bin`. The
  generated script loads whichever was written.
* **`pyplot -export [name] sig1 sig2 …`** writes the table and nothing else —
  no script, no Python — and reports `pyplot: exported sig.npy (301 rows,
  4 columns)`. It goes through plotit like the other markers, so expressions,
  `vs` and plot-qualified names work; combined with `-hist`, `-contour`,
  `-smith`, `-fft`, the AC views or `-eye` it is refused with the reason,
  since each of those writes its own table beside its plot.
* **`help pyplot`** lists every mode and the main settings instead of one
  line.
* The crashfix2 suite's `contour.py` and `contour.data` were regenerated
  artefacts committed by mistake in an earlier enhancement and churned with
  every generator change; they leave tracking and the suite cleans them up.
  `.gitignore` gained a `.npy` rule beside every pyplot `.data` rule.

## Measured

A million-point, four-trace export (the simulation alone takes 1.9 s):

| | `.npy` | ASCII |
|---|---|---|
| ngspice, end to end | 2.05 s | 4.49 s |
| file size | 64 MB | 170 MB |
| loaded in Python | 7 ms | 420 ms |

## Verification

| check | result |
|---|---|
| the default table | `<name>.npy`, fields `('time', 'v(out)', 'time_2', 'v(in)')`, exact, the script renders |
| `pyplot_export=ascii` | `<name>.data` with the `#` header, the script loads it |
| `pyplot -export sig v(out) i(v1)` | `sig.npy`, no script, the message; `vs` names the x column |
| `-export -hist` | refused with the reason |
| `-contour`, `-smith`, `-bode` tables | their own field names |
| the `.npy` layout | magic, version 1.0, 64-byte-aligned header, rows × columns doubles |
| `pyplot_examples` | 35 / 35, both solvers |
| full sweep | 455 of 455 |
