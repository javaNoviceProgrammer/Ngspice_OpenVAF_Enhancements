# openvaf-r autodiff audit: hypot, atan2 & real-modulo derivative fixes (Enhancement-185 / 186)

The compiler builds the small-signal **Jacobian** — used by AC analysis,
Newton convergence, noise, pole-zero, and every derivative-dependent result —
with its own automatic differentiation (`mir_autodiff`). An audit compared the
AC small-signal conductance `g = dI/dV` of a battery of nonlinear laws
`I = f(V)` against the **analytic** `f'(V)`, and found three builtins whose
*value* is correct (so DC is right) but whose *derivative* was wrong — the
classic "accidental correctness" pattern that DC-only tests miss.

## The three bugs

- **`hypot(x,y)`** — the autodiff rule computed `(x' + y')/(2·hypot)` (the
  `sqrt` pattern misapplied) instead of the correct `(x·x' + y·y')/hypot`. At
  V=0.7, y=0.5 it returned `0.581/hypot` where the answer is `0.7/hypot` — 28%
  off. It was only *accidentally* correct at x=0.5 (with y constant), which is
  exactly where a naive spot-check would land. *(Enhancement-185)*

- **`atan2(x,y)`** — two bugs in the cached factors that feed the shared
  `Pow|Atan2` chain rule `(x'·c₀ + y'·c₁)·c₂`: the common factor `c₂` was
  `(x²+y²)` where the rule *multiplies* by it, so it needed the **reciprocal**
  `1/(x²+y²)`; and the second-argument factor `c₁` was `+x` where the
  derivative *subtracts*, so it needed `−x`. The result was wrong in magnitude
  **and** sign for the second-argument derivative. *(Enhancement-185)*

- **real modulo `%` (`Frem`)** — `x % c = x − floor(x/c)·c` is a slope-1
  sawtooth in `x`, so `d/dx(x % c) = 1` away from the wrap points. But the
  opcode was grouped with `floor`/`ceil`/integer ops and forced to derivative
  **0** in *both* the live-derivative gate (`lib.rs`, which decides which
  values even depend on the unknown) and the chain rule (`builder.rs`). A model
  using real modulo — phase wrapping, periodic geometry — got a correct DC
  value but a **zero AC / Jacobian contribution**. The correct rule, including
  a bias-dependent divisor, is `d/du(x % c) = x' − floor(x/c)·c'` (folding to
  just `x'` for a constant divisor). *(Enhancement-186)*

All three are fixed in `mir_autodiff` (`builder.rs` + `lib.rs`).

## Why it matters

`hypot`, `atan2`, and real modulo appear in real compact models — `hypot` for
smoothed `sqrt(x²+ε²)` turn-ons and velocity-saturation terms, `atan2` for
phase and geometry, `%` for phase wrapping and periodic structures. A model
using any of them would give a **correct DC operating point but a silently
wrong AC response, small-signal gain, and convergence Jacobian**.

## Verification

`verify_vafautodiff.py` recompiles a battery of laws and reads the AC
conductance:

- `hypot` d/dV in both argument orders equals `V/hypot`, equals the
  hand-expanded `sqrt(V²+0.25)` derivative, and is still correct at the V=0.5
  accidental-correctness point;
- `atan2` d/dV equals `x/(x²+y²)` / `−y/(x²+y²)` (magnitude and sign), and
  `atan2(V,V)` (constant π/4) differentiates to 0;
- real modulo `d/dV(V % c) = 1` for two divisors, scales with the prefactor,
  flows through a chain rule (`d/dV(V%1)² = 2·(V%1)`), and leaves `floor`/`ceil`
  (genuinely piecewise-constant) at 0;
- the fix reaches a **reactive** charge (`ddt(hypot…)`) via the AC susceptance;
- a regression battery of 15 other math builtins (sin/cos/tan, the inverse and
  hyperbolic families, exp/ln/log/sqrt, pow) confirms their derivatives were
  already correct and are undisturbed.

It is a compiler property, identical under both linear solvers, so it runs once.

## Running

```sh
python3 verify_vafautodiff.py
openvaf-r hypot_demo.va -o hypot_demo.osdi && ngspice -b hypot_demo.cir
```
