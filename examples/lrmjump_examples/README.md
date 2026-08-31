# lrmjump — jump statements & the Annex C/E boundary (Enhancement-520)

An LRM-2023 audit of the **Annex C** subset boundary and **Annex E** SPICE
compatibility found a compiler crash, a missing 2023 feature, and a
load-refusal against a mandated fallback. This suite pins the fixes:

- **Jump statements** (5.11): `break`/`continue`/`return` — new in
  VAMS-2023 — work through every loop kind: `continue` re-enters a `for` at
  its increment and still counts a `repeat` iteration, `break` leaves only
  the innermost loop, `return [expr]` exits an analog function from nested
  statements. All checked numerically. Position rules enforced: outside a
  loop, inside a genvar `analog_for` (5.9.3), or `return` outside a function
  are targeted errors. The keywords are **contextual** — legacy identifiers
  named `break` still compile, flagged by L012.
- **String analog functions** (4.7.1, Mantis 7808): string return type and
  string output arguments — both ICEd the compiler.
- **`$limit` fallback** (9.17.3): an unknown limiter name loads with a
  warning and no limiting ("as if no string had been supplied") instead of
  refusing the whole `.osdi`; Table E.2's preferred name `vdslim` is an
  alias of `limvds` and really limits.
- **2023 deprecations audible**: `$realtime` in the analog context warns
  (Table 9-7; behaves as `$abstime`), and `` `default_discipline `` warns as
  an ignored AMS-only directive (C.4) instead of being silently swallowed.

Run `python3 verify_lrmjump.py` — 22 checks, both solvers.
