# Enhancement-580: `hypot` and `atan2` have a finite derivative at the origin

**Scope:** the 2026-09-07 hunt's F1
([`docs/bug_hunts/2026-09-07_openvaf-r-language-semantics.md`](../docs/bug_hunts/2026-09-07_openvaf-r-language-semantics.md)):
two derivative caches in `openvaf/mir_autodiff/src/builder.rs`. Alongside it the hunt's
F2 is withdrawn as a defect in the hunt report itself — see below. **OpenVAF-r only.**

**Suites:** new [`hypotzero_examples`](../examples/hypotzero_examples/) (15 checks per
solver, both solvers; 11 of 15 pass against the shipped compiler); full sweep 479 of
479. Crate tests `mir_autodiff`, `mir_opt`, `sim_back`, `hir_lower` and `openvaf` with
`llvm18`: 60 of 60.

## F1 — `hypot(x, y)` and `atan2(y, x)` had a NaN derivative at (0, 0)

`hypot` was differentiated as `(x·x' + y·y') / hypot(x, y)` with the cache being
`hypot(x, y)` itself: 0/0 at the origin. `atan2(y, x)` cached `1/(x² + y²)`, +∞ at the
origin, multiplied by `x'·y − y'·x = 0`: also NaN. V = 0 is ngspice's DC initial guess,
so a model with a contribution built on `hypot` or `atan2` of node quantities — an
amplitude from two quadrature voltages, a phase from two currents — put a NaN into the
Jacobian on its first Newton iteration and failed every operating-point method the
simulator has: dynamic gmin stepping, true gmin stepping, source stepping and the
transient op, in that order. `abs`, `sqrt` and `pow` at zero had all been guarded for a
long time (Enhancement-261's `sqrt(x + 1e-18)`, the `x + 1e-18` shift in the `pow`
cache); these two were left out. A constant zero argument hid the `atan2` half:
`atan2(V, 0.0)` folds the constant away before the chain rule runs, so the hunt's own
probe with a literal 0 passed while two node voltages fail.

The caches are regularised the way `sqrt`'s was: `hypot(hypot(x, y), 1e-18)`, that is
`sqrt(x² + y² + 1e-36)`, and `1/(x² + y² + 1e-36)`. Both are finite at the origin — the
derivative there is 0, the value of the smooth |x| — and for any radius above 1e-9 and
1e-10 respectively the perturbation is below the ULP, so every derivative away from the
origin is unchanged: the suite pins the slopes at (0.3, 0.4) and at a radius of 1e-6 to
1e-12.

## F2 — withdrawn: the random draw's fixed seed is a documented design, examined twice before

The hunt reported that `$random(seed)` and the `$rdist_*` functions never write the
seed back, that re-seeding does not restart a sequence, and that a call site draws once
per instance and returns that number on every later evaluation. All three observations
are correct, and all three are the deliberate contract:

- [Enhancement-10](Enhancement-10.md) made every draw a pure function of `(seed value,
  call-site salt, parameters)` with no write-back, and says why in its §1 and in
  `examples/rng_examples/README.md`: a seed that advances in place returns a different
  number on every Newton iteration.
- [Enhancement-395](Enhancement-395.md) wrote the LRM write-back fix and measured it: a
  body-level `x = $rdist_normal(seed, 1.0, 0.5)` then fails dynamic gmin stepping, true
  gmin stepping, source stepping and the transient op, and the run aborts. The fix was
  withdrawn and lint **L019** (`rng_in_loop`) added instead, naming the call, the
  constancy and the reason.
- [Enhancement-539](Enhancement-539.md) corrected an external audit that had reported
  the same behaviour as an undiagnosed defect.

The LRM's inout seed describes a procedural language; a seed read inside a residual that
is re-evaluated to convergence is a different problem, and the pure form is what makes
Monte Carlo reproducible and per-instance variation independent. What the hunt did not
see is that its probes were not in loops, so L019 had nothing to say. Nothing changes in
the compiler; the hunt report now records F2 as by design with the three references, so
the next reader does not re-derive it a fourth time.

## Verification

`hypotzero_examples` compiles one module with `hypot(V, 0)`, `hypot(Va, Vb)`,
`atan2(Vb, Va)`, their sum, `abs(V)`, `sqrt(V·V)` and `sqrt(V)` as selectable
contributions and, on both solvers: solves the operating point at the origin for the
four `hypot`/`atan2` forms with a zero small-signal conductance (the shipped compiler
fails all four); reads the AC conductance at (0.3, 0.4) as 0.6, −1.6 and −1.0, at (0.5, 0)
as 1, and at a radius of 1e-6 as x/h to 1e-12; keeps the neighbours' slopes (1, 0, the
large finite E-261 value); and runs two transients that sweep a node through the origin.
