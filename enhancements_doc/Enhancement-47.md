# Enhancement-47 — `default_transition + transition() fixes

This document describes the changes made to **OpenVAF-r** in the `version11/`
directory to implement the **`` `default_transition``** compiler directive and
fix two pre-existing `transition()` defects the work exposed. Front-end +
lowering only; no OSDI/ngspice change.

## The directive (was a hard error)

`` `default_transition <time>`` sets the default rise/fall time used by
`transition()` filters that omit those arguments (LRM; 0 = instantaneous when
no directive is given). Previously it hard-errored as an undeclared macro —
the only directive from the E-47 probe's list of nine that didn't work
(`define`/`undef`/`ifdef`/`ifndef`/`else`/`elsif`/`endif`/`include` were all
verified exact).

**Implementation**:

- `preprocessor`: a `DefaultTransition` directive kind (next to
  `DefaultDiscipline`), a capture-number helper, and an SI-suffix-aware value
  parser (`1u`, `10n`, `1e-6`, `_` separators). The value rides on the
  `Preprocess` result (last directive wins — file-level granularity; real
  models declare at most one, and a directive inside a false `` `ifdef``
  is never processed, so conditional guards behave correctly).
- `hir/db.rs`: `CompilationDB::default_transition()` accessor.
- `hir_lower`: the no-args and delay-only `transition()` forms ramp with the
  directive's time (rate = 1/t) instead of returning the input directly;
  explicit rise/fall arguments are untouched.

## Pre-existing defect #1: the TRANSITION signature table (compiler crash)

Every entry was one argument short: `TRANSITION_DELAY_RISET` claimed 2
arguments (it takes 3), `_FALLT` 3 (takes 4), `_TOL` 4 (takes 5). So a
3-argument `transition(s, td, trise)` resolved to `_FALLT` and the lowering
read `args[3]` **out of bounds — compiler crash** (confirmed on the released
E-46 binary); 4-argument calls only worked *by accident* (they resolved to
`_TOL`, whose lowering happened to read the right indices); the true
5-argument tol form did not resolve at all. The table now declares the correct
arities and all five forms work.

## Pre-existing defect #2: singular DC operating point

`lower_rate_limited_track` (shared by `slew` and `transition`) implements
`dy/dt = clamp(K·(x−y), −fall, rise)`. When the clamp saturates, the residual's
derivative w.r.t. `y` is **zero** — and since the reactive part doesn't count
in DC, the Jacobian diagonal vanished and the operating point went singular
whenever the input started more than `rate/K` away from the state (e.g. a
timer-driven comparator already high at t=0): gmin/source stepping failed and
the transient produced garbage unless `uic` was given. Per the LRM a
transition/slew filter is a static **identity in DC**, so the residual now
selects on the integration-enable parameter: `y − x` in DC (diagonal 1, never
singular, exact LRM semantics), the rate-limited form in transient. AC also
becomes an exact unity transfer (previously a spurious pole at K = 1e9 rad/s).

## What now works (`defaulttransition_examples/`, all verified)

| case | result |
|---|---|
| bare `transition(s)` + `` `default_transition 1u`` | 1 µs ramp, half-cross at 0.5 µs, clean DC (no `uic`) |
| `transition(s, 0.2u)` + directive | delay then default ramp (half-cross at flip + 0.7 µs) |
| explicit `transition(s, 0, 2u)` | 2 µs ramp — explicit args win |
| all five arities in one contribution | weighted plateau 0.875 exact (3-arg used to crash) |
| no directive | instantaneous, unchanged |
| directive inside false `` `ifdef`` | ignored |

`verify_defaulttransition.py`: 8/8 PASS. Regression: all 43 example verify
suites ALL PASS; 71/71 crate tests.

## Notes

- Positional granularity is file-level (the last directive processed wins),
  matching real usage; the LRM's mid-file re-declaration subtlety is out of
  scope.
- The absdelay history's startup value (input nonzero at t=0 reads 0 for the
  first `td`) is a pre-existing E-24 behavior surfaced while testing, not
  changed here.
