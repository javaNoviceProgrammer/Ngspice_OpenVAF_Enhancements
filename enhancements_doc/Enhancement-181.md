# Enhancement-181 — core-numerics audit: the integrator certified exactly, plus `.options ordfix`

The gap-analysis "Core numerics" table has carried ✅ marks for the integration methods since the beginning — but nobody had ever verified that ngspice's Gear (BDF) corrector coefficients actually deliver their nominal order. Orders 3–6 were dead code for ~30 years until [E-128](Enhancement-128.md)'s `dynorder` selected them, and E-128 verified order *selection*, not coefficient *correctness*. This audit closes that: the coefficients are now certified **exactly**, a new verification instrument ships, and the rest of the table (solver precision, convergence aids, the ancient `xmu`/`lvltim` paths) is referee-verified with no defects found.

![corenum](../examples/corenum_examples/corenum.png)

## Why this needed an instrument

Three successive measurement traps — each initially looking like a bug — turned out to be real numerics, and are now documented:

1. **Loose tolerances invert the order preference.** The LTE-limited step is `h_k = (c_k·tol)^{1/(k+1)}`: for effective tolerance ≫ 1 it *decreases* with order, so the E-128 controller's refusal to climb under a pinned step with loose `reltol`/`trtol` is correct-by-theory, not a freeze.
2. **The order-1 first step** proportional to the pinned step imposes an O(h²) startup error floor that masks every order above 2 — the classic BDF-starter problem.
3. **Step-ratio stability**: ramping ×2 at order 6 visibly seeds divergence (variable-step BDF instability at large ratios), and a lossless LC sits outside BDF≥4's A(α) wedges — the observed gear6 blow-ups during the audit were *textbook-correct* behavior of correct coefficients.

`.options ordfix=K` is the shipped instrument: it pins the Gear order at K for verification runs — every converged step is accepted (the step is ruled by `tmax`, not the LTE), the first step is shrunk 1000×, the order ramps to K while the step is still tiny, and the step then grows gently (×1.15) to the pin. Off by default; useless (deliberately) for production runs.

## The certification

With `ordfix`, the referee is airtight and startup-independent: dump the accepted trajectory at full precision and check, at every stencil of k+1 uniformly spaced points, that ngspice's values satisfy the **exact BDF-k formula** — Lagrange differentiation on the actual nodes — for the circuit ODE. Result: **max residual ≤ 1.3e-13 at every order 1–6** (~90 stencils each). `NIcomCof`'s coefficients are exactly right at all orders, variable-step machinery included. Measured global convergence confirms orders 1–3 asymptotically (trap 1.87, gear1 0.90, gear2 1.87, gear3 2.78 at the finest pair), and the trap-vs-Gear dissipation dichotomy on a lossless LC matches theory: trap preserves the amplitude (|R(iy)| = 1) while Gear damps it, less at higher order.

## The rest of the table — no defects

- **Linear-solve precision** (both solvers): errors track conditioning theory (κ·ε on a 1e6-spread ladder); a 1e18-conductance-spread asymmetric mesh with a VCCS solves to 1e-15 against an exact-rational MNA referee; KLU ≈ Sparse throughout.
- **DC convergence aids**: on a 40-diode hard-DC chain, default / `noopiter` / `gminsteps=0` / `srcsteps=0` all land on the same operating point (spread ≤ 2.2e-6 — tolerance-level), and KLU ≡ Sparse to 7e-13 — the two solvers' separate gmin-diagonal-loading paths in `NIiter` agree.
- **`xmu`**: 0.5 is bit-identical to plain trap; 0.45 damps the lossless ring as documented.
- **`lvltim=1`** (iteration-count timestep control, rarely exercised): works, agrees with the default LTE control.

A pre-existing `-Wmissing-prototypes` warning (`DCtran_step_quit`, declared `extern` locally in runcoms2.c) is silenced with a proper header prototype.

## Verification

[`examples/corenum_examples/verify_corenum.py`](../examples/corenum_examples/verify_corenum.py) — 8 checks × both solvers: the BDF-residual certification (orders 1–6, ≤1e-12), measured convergence slopes, the LC dissipation conformance, the hard-DC aid matrix, the exact-rational precision mesh, `xmu`, `lvltim=1`, and the `ordfix` order report. The E-128 `dynorder` suite passes unchanged. Full example regression: 149/149.
