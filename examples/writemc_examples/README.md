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

Run: `python3 verify_writemc.py` (15 checks per solver, both solvers).
