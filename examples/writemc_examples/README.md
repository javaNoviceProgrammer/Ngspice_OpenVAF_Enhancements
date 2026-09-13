# writemc_examples — Enhancement-611

`.option savemc` writes one row per analysis run with the draws behind it;
what the `.control` block computes from the run came after that row. Now the
row of the last run stays addressable: `writemc [name=]<expression> ...` puts
each (scalar) value onto it after a run in a `repeat`/`reset` loop, and
`montecarlo ... -writemc [name=]<expr> ...` does it per sample, after the
tracks, specs and exprs, so an `-expr` name or a `track<k>.<vector>` may be
listed. A column is added on first use; the csv's last line is rewritten in
place, so the file stays complete row by row. On the way, `x[0]` on a
one-point vector is now its element (it was "indexing a scalar"), which
`track1.time[0]` needs on every sample with exactly one hit.

Three more checks came from driving the shared library from a schematic
front end, whose nets are spelled `/name` and whose own run is a plain `.op`: `v(/mid)/v(/in)` now evaluates in
`writemc`, `-writemc`, `-expr`, `-spec` and `sweep -output` (the auto-quoting
`print` and `plot` already had); a `.model` card whose parameter draws is a
`<model>:<key>` column on a plain run as well as on montecarlo's fast path; and
`montecarlo N -analysis op -writemc ...` with nothing else to judge or record
is a run, not "nothing to do".

Enhancement-624 (F8 of the 2026-09-12 hunt): `writemc` lands only on the row
of the run whose plot it reads. A trial whose `op` was refused at setup (a
draw outside the model's range) made no plot and left the previous run's plot
current, so its `failed` row carried the previous trial's value; every row now
remembers the plot its run made, and a `writemc` whose current plot is not the
row's own (nor an older one chosen with `setplot`) is refused with the row and
plot named -- the cell stays empty, as `montecarlo -writemc` leaves it on a
failed sample. A transient that died part-way keeps its partial plot and still
records from it; a run stopped at a breakpoint has no row and its plot is
refused (check [13]).

Run: `python3 verify_writemc.py` (18 checks per solver, both solvers).
