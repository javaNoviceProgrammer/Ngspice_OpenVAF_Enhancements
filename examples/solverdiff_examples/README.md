# Sparse 1.3 vs KLU — differential campaign

37 checks comparing the two linear solvers on circuits where the solve is
actually hard: ill-conditioned networks and stiff nonlinear ones.

## This is not part of the regression suite — on purpose

`examples/run_regression.py` discovers `examples/*_examples/verify_*.py`. This
driver is named `run_solverdiff.py`, so the routine sweep never picks it up.

```bash
cd examples/solverdiff_examples
python3 run_solverdiff.py          # both phases
python3 run_solverdiff.py 1        # phase 1 only
```

Phase 1 needs `numpy` for its third opinion; without it that phase is skipped
with a message rather than failing.

## Why it exists

Other suites already run both solvers and require them to agree — but on small,
well-conditioned circuits, where agreement proves very little. This one targets
the regime that actually distinguishes them: **Sparse re-pivots** (measured at
~12–15 forced reorders per Monte Carlo sample) while **KLU computes its symbolic
ordering once** and only refactors numerically.

## The method, which is the point

**A solver-vs-solver diff says they differ; it cannot say which is wrong.**

- **Phase 1 (linear).** The nodal system *is* the MNA matrix, so `numpy` solves
  the same system independently and becomes the third opinion. Every deck reports
  its **condition number**, and the tolerance is `eps·cond` — a disagreement is
  read against how hard the problem actually is. Decks whose cond exceeds what
  float64 can deliver are **reported, never asserted**: a tolerance that grows
  without limit is a rubber stamp, not a test.
- **Phase 2 (nonlinear/stiff).** No closed form for most, so the references are
  solver-vs-solver at tight tolerance, a **tightened-`reltol` run** (which
  separates a linear-solve difference from mere convergence slack), and closed
  form for the single diode.

Families are built so **pivoting matters**: `ladder_ratio`, `star` (a dense
matrix row), `weak_couple`, `near_float`, `wide_range`, each swept over 0–12
decades; then diode ladders (up to 600 diodes, up to 5 V), MOSFET chains (up to
300), diodes shunted by resistors spanning 10⁶–10¹⁸, and every analysis —
`op`, `dc`, `ac`, `tran`, `noise`, `tf`, `pz`.

## Result when last run (2026-07-27): 37/37, no solver defect

Worst Sparse-vs-KLU disagreement **anywhere** was `7.06e-06`, on cond `2.4e12`
where `eps·cond` is `5e-4` — comfortably inside what float64 permits.

Two findings worth more than the pass count:

- Both solvers track the exact solution **in step with conditioning**, and they
  **trade places** — Sparse more accurate on `ladder_ratio`, KLU on `star(9)`.
  That is what differing pivot orders should look like, and it rules out
  systematic bias either way.
- On the stiff nonlinear decks they agree to **1e-18 … 1e-13**, including the
  600-diode ladder at 5 V where Sparse is constantly re-pivoting.

**Sparse is numerically sound where float64 allows.** Its real weakness is
robustness and cost, not accuracy — it re-pivots 12–15× per Monte Carlo sample
and is ~210× slower than KLU on a 500-device MC benchmark. That gap is
architectural; see `Enhancement-343`/`-345` and the notes on `.option klu`.

## Harness traps

Every one of these produced a **false green or a false red** before being caught.
They are the main reason this file is worth keeping:

1. The first version reported **25/25 and meant nothing**: `star` had `cond =
   1.0` (the hub was the only unknown — a 1×1 matrix), and `tol = 5e-16·cond`
   ballooned to `1.3e+03`, auto-passing anything.
2. Normalising error by `max|exact|` **across** nodes hides a large relative
   error on a small node. Use per-node relative error with an absolute floor.
3. A crude `eps·span` bound **underestimated true cond by ~450×**, because diode
   small-signal conductance dominates the matrix. Compute cond of the
   **linearised** system at the operating point instead.
4. The closed-form diode oracle needs ngspice's **own** thermal voltage,
   `0.0258649170072` — measured from its I-V curve, and matching the OSDI
   campaign's independent measurement to 12 digits. `CONSTboltz/CHARGE` is
   0.24 ppm away and shows up as a 7.6e-4 current error.
5. `pz` prints a **complex pair** `re,im`; a regex requiring end-of-line after
   the first number silently yields "no result". Separately, `pz` does not
   converge on a 120-node ladder — identically on **both** solvers, so that is a
   `pz` scale limit, not a differential finding.
