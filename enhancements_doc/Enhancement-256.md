# Enhancement-256 — no silent spurious DC operating point for singular-derivative behavioral sources

A deep DC-solver correctness fix. A behavioral source whose small-signal
derivative is **infinite at the v = 0 initial guess** — `B I=sqrt(v(n))`,
`I=0.1/v(n)`, `I=ln(v(n))`, `v^0.5`, … — could make ngspice **silently report a
wrong DC operating point** that grossly violates KCL, with no warning.

## The bug

At ngspice's default all-nodes-at-zero initial guess, `sqrt(v)` has conductance
`dI/dv = 0.5/√v → ∞`. That huge Jacobian entry pins the node at `v ≈ 0`, so Newton
takes a vanishing step. The convergence test — which checks only the
**iterate-to-iterate voltage change** — sees no change and declares "converged",
at a point where the resistor pushes a full current into the node and the source
sinks ≈ 0 (a 0.4 A KCL violation on a `0.6 V / 1 Ω` divider). Worse, this **false
convergence pre-empted the gmin/source-stepping fallbacks**: they never ran,
because ngspice believed it had already converged. The result was silently wrong
and *data-dependent* (`i=1m*sqrt(v)` converges fine; a `.nodeset` finds the true
root), so it was easy to miss. A related crash path: `pwr(0, negative)` and the
derivative of `v^b` returned raw `+inf`, poisoning the Jacobian into `NaN` and a
"DC solution failed".

The AC/derivative machinery itself is correct — the B-source small-signal
conductance `dI/dv` matches the analytic derivative to ~1e-10 across the whole
function library. The defect is purely the DC **convergence** accepting a
KCL-violating point.

## The fix

Three coordinated pieces:

1. **False-convergence guard (`maths/ni/niiter.c`).** After the voltage-change
   test declares convergence, also check the **KCL residual** `F = G·x − b` (the
   node-current imbalance; already computed for the E-111 line search). If the
   worst node imbalance is `> 100×` the current-convergence tolerance, the point
   is spurious — decline convergence so `CKTop` falls through to gmin/source
   stepping, which regularizes the singular node and finds the **true** operating
   point. The separation is decisive: a false convergence sits at merit `≈ 1/reltol
   ≈ 1000`, every legitimate circuit at `< 1` (measured `1e-7 … 0.35`), so the
   `100×` threshold is result-neutral on well-behaved circuits.

2. **First-attempt isolation (`cktdefs.h`, `spicelib/analysis/cktop.c`).** A new
   `CKTdcFirstTry` flag is set by `CKTop` *only* around the initial plain-Newton
   attempt. The guard fires only then, so it never interferes with the convergence
   aids' own sub-solves — gmin stepping, source stepping, pseudo-transient
   continuation / `optran` (E-127/E-204) all run exactly as before. (This was
   essential: an earlier, unconditioned version broke `convhelp`, `ptcont`,
   `corenum`, and `tempphys` by firing inside their homotopies.)

3. **`pwr(0, negative)` guard (`spicelib/parser/ptfuncs.c`).** Return the
   parser's `HUGE` sentinel instead of raw `+inf`, matching the existing `/0`
   (`PTdivide`) and `√neg` (`PTsqrt`) guards, so a singular derivative stays finite
   rather than turning the Jacobian into `NaN`.

Net effect: `B I=sqrt(v(n))` and `I=0.1/v(n)` now converge to the correct
operating point (both solvers, realistic loading, multi-node); every existing
convergence path is untouched.

## Verification

`examples/bsrcconv_examples/verify_bsrcconv.py` (both solvers):

1. `I=sqrt(v(n))` DC op is the analytic solution `v0=0.178045` with KCL satisfied
   (`i_B1 == i_R1`), **not** the spurious `v≈0` (which had a 0.42 A imbalance);
2. `I=0.1/v(n)` reaches the analytic upper-branch root `v0=0.887298`;
3. **result-neutral**: finite-derivative behavioral sources (`v^2`, `v^3`, `exp`,
   `tanh`) converge to their exact operating points, unchanged.

The full regression — including the convergence-aid suites `convhelp`, `ptcont`,
`corenum`, `tempphys` — passes on both solvers.

## Scope

DC-solver Newton loop (`niiter.c`) + a one-bit `CKTcircuit` flag managed by
`cktop.c` + a parser math guard (`ptfuncs.c`); the ngspice binary is rebuilt. The
change is confined to the first plain operating-point attempt and is
result-neutral for every circuit that already converged.
