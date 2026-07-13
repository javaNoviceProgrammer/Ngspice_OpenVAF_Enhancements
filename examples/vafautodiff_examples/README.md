# openvaf-r autodiff audit: hypot & atan2 derivative fixes (Enhancement-185)

The compiler builds the small-signal **Jacobian** — used by AC analysis,
Newton convergence, noise, pole-zero, and every derivative-dependent result —
with its own automatic differentiation (`mir_autodiff`). An audit compared the
AC small-signal conductance `g = dI/dV` of a battery of nonlinear laws
`I = f(V)` against the **analytic** `f'(V)`, and found two builtins whose
*value* is correct (so DC is right) but whose *derivative* was wrong — the
classic "accidental correctness" pattern that DC-only tests miss.

## The two bugs

- **`hypot(x,y)`** — the autodiff rule computed `(x' + y')/(2·hypot)` (the
  `sqrt` pattern misapplied) instead of the correct `(x·x' + y·y')/hypot`. At
  V=0.7, y=0.5 it returned `0.581/hypot` where the answer is `0.7/hypot` — 28%
  off. It was only *accidentally* correct at x=0.5 (with y constant), which is
  exactly where a naive spot-check would land.

- **`atan2(x,y)`** — two bugs in the cached factors that feed the shared
  `Pow|Atan2` chain rule `(x'·c₀ + y'·c₁)·c₂`: the common factor `c₂` was
  `(x²+y²)` where the rule *multiplies* by it, so it needed the **reciprocal**
  `1/(x²+y²)`; and the second-argument factor `c₁` was `+x` where the
  derivative *subtracts*, so it needed `−x`. The result was wrong in magnitude
  **and** sign for the second-argument derivative.

Both are fixed in `mir_autodiff/src/builder.rs`.

## Why it matters

`hypot` and `atan2` appear in real compact models — `hypot` for smoothed
`sqrt(x²+ε²)` turn-ons and velocity-saturation terms, `atan2` for phase and
geometry. A model using either would give a **correct DC operating point but a
silently wrong AC response, small-signal gain, and convergence Jacobian**.

## Verification

`verify_vafautodiff.py` recompiles a battery of laws and reads the AC
conductance:

- `hypot` d/dV in both argument orders equals `V/hypot`, equals the
  hand-expanded `sqrt(V²+0.25)` derivative, and is still correct at the V=0.5
  accidental-correctness point;
- `atan2` d/dV equals `x/(x²+y²)` / `−y/(x²+y²)` (magnitude and sign), and
  `atan2(V,V)` (constant π/4) differentiates to 0;
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
