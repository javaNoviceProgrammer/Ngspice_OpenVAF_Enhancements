# hunt17diag_examples — Enhancement-665

The diagnostic slips and run-time silences of the bug hunt of 2026-09-18
(findings F11, F12, F13 and F15), each pinned end-to-end: malformed number
literals (`1e3n`, `0.5e`, `1meg`), the summary naming an elaborated copy, a
nature whose access function carries its own name, `forever` in an analog
block, a non-ASCII identifier, `(* desc= *)`, an undeclared macro's knock-on,
`corner="ss=0.5 %"`, a string parameter's default outside its own set, an
escaped identifier exported with a `+`, the nesting-limit cascade on a flat
sum, and `absdelay`/`$bound_step` with a deck-fixed negative argument. Two
hunt items are pinned as expected behaviour instead: the text after an
`` `ifdef `` name is the conditional group, and `$discontinuity(-1)` is the
limiting-discontinuity marker.

Run: `python3 verify_hunt17diag.py` (20 checks per solver, both solvers).
