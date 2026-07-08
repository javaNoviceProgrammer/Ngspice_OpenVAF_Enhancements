# pyplotexport_examples — pyplot SVG/PDF export + figure size (Enhancement-99)

Two additions to the `pyplot` command (E-94/95/98): `set pyplot_terminal=svg`
and `set pyplot_terminal=pdf` render the plot headless (matplotlib Agg) to a
vector `<file>.svg` / `<file>.pdf` — the same mechanism as the E-94 `png`
terminal, extended to matplotlib's native vector writers. `set
pyplot_figsize="W,H"` sets the figure size in inches (quote the value so
ngspice keeps the comma; a space or `x` separator inside the quotes also
works).

The verify renders an RC transient with `pyplot_terminal=svg` +
`pyplot_figsize="8,3"`, `pyplot_terminal=pdf`, and `pyplot_terminal=png`; it
checks each output by magic bytes (`<?xml`, `%PDF`, `\x89PNG`) and the
generated scripts for `figsize=(8, 3)` when set / no `figsize=` when unset.
Requires matplotlib. Run: `python3 verify_pyplotexport.py` (5 checks).
