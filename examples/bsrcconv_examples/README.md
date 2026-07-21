# No silent spurious DC operating point for singular-derivative B-sources (Enhancement-256)

A deep DC-solver correctness fix. A behavioral (`B`) source whose small-signal
derivative is **infinite at the v = 0 initial guess** — `I=sqrt(v(n))`,
`I=0.1/v(n)`, `I=ln(v(n))`, `v^0.5` — could make ngspice **silently report a wrong
DC operating point** that grossly violates KCL, with no warning.

## The bug

`sqrt(v)` has conductance `dI/dv = 0.5/√v → ∞` at ngspice's default v = 0 initial
guess. That huge Jacobian entry pins the node at `v ≈ 0`; Newton takes a vanishing
step; the convergence test (which checks only the iterate-to-iterate **voltage
change**) sees no change and declares "converged" — at a point where a resistor
pushes a full current into the node and the source sinks ≈ 0 (a 0.42 A KCL
violation on a `0.6 V / 1 Ω` divider). The false convergence also **pre-empted the
gmin/source-stepping fallbacks**, which would have found the true root. It was
silent and data-dependent (`i=1m*sqrt(v)` converges fine), so easy to miss.

## The fix

After the voltage-change test declares convergence, ngspice now also checks the
**KCL residual**; if the worst node-current imbalance is `> 100×` the tolerance
(a false convergence sits at `≈ 1000×`, every real circuit at `< 1×`), it declines
the point so the existing gmin/source-stepping aids engage and find the true
operating point. The check is confined to the first plain-Newton attempt (via a
`CKTdcFirstTry` flag), so every convergence aid — gmin/source stepping,
pseudo-transient continuation, `convhelp`, `optran` — runs exactly as before. A
companion parser guard stops `pwr(0, negative)` returning raw `+inf`.

## Verification

`verify_bsrcconv.py` (both solvers):

1. `I=sqrt(v(n))` reaches the analytic `v0 = 0.178045` with KCL satisfied, not the
   spurious `v ≈ 0`;
2. `I=0.1/v(n)` reaches the analytic upper-branch root `v0 = 0.887298`;
3. **result-neutral**: finite-derivative sources (`v²`, `v³`, `exp`, `tanh`)
   converge to their exact operating points, unchanged.

The full regression — including the convergence-aid suites (`convhelp`, `ptcont`,
`corenum`, `tempphys`) — passes on both solvers.

## Scope

DC Newton loop (`niiter.c`) + a one-bit `CKTcircuit` flag (`cktdefs.h`,
`cktop.c`) + a parser math guard (`ptfuncs.c`); the ngspice binary is rebuilt.
Confined to the first operating-point attempt; result-neutral for every circuit
that already converged.
