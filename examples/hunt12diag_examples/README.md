# hunt12diag_examples — Enhancement-634

The diagnostic findings D1–D24 of the 2026-09-12 hunt, each pinned: the seed's
32-bit range (D1), `set controlswait` under `-b` (D2), the fixed columns of a
`savemc` row (D3), `highsigma` with nothing to inflate (D4), a statistics
attribute given twice (D5, compiler), an option card given twice and
`automc_save` beside `savemc` (D6), `writemc` after a row-less run (D7),
`autoadapt` without `adapter=` (D8), a model parameter on the instance line
(D9), a recentre outside the declared range (D10), the OSDI flow vector's type
and name (D11), the txt writer's empty cell (D12), a bus wider than its port
(D13), a `setseed` set aside (D14), `wcd`'s rows labelled (D19), statistics
on a discrete-valued parameter (D21, compiler), and the `-inflate` spelling of
a device inside a subcircuit (D24).

Run: `python3 verify_hunt12diag.py` (20 checks per solver, both solvers).
