# Enhancement-185 — openvaf-r autodiff audit: hypot & atan2 derivative fixes

A deep audit of the openvaf-r compiler's **automatic differentiation** — the pass (`mir_autodiff`) that builds the small-signal Jacobian used by AC analysis, Newton convergence, noise, pole-zero, and every derivative-dependent result. The probe compared the AC small-signal conductance `g = dI/dV` of a large battery of nonlinear laws `I = f(V)` against the *analytic* `f'(V)`, and caught two builtins whose **value is correct** (so the DC operating point is right) but whose **derivative was wrong** — the fifth occurrence of the accidental-correctness pattern this project keeps finding ([E-171](Enhancement-171.md)/[175](Enhancement-175.md)/[177](Enhancement-177.md)/[178](Enhancement-178.md)/[179](Enhancement-179.md)), and the first on the compiler side.

## `hypot(x,y)` — wrong derivative formula

The autodiff rule computed `(x' + y')/(2·hypot(x,y))` — the `sqrt(x)` pattern (`x'/(2·sqrt)`) misapplied to a two-argument function. The correct derivative of `hypot(x,y)=√(x²+y²)` is

```
d/du hypot(x,y) = (x·x' + y·y') / hypot(x,y)
```

At V=0.7, y=0.5 the old code gave `1/(2·0.860) = 0.581` where the answer is `0.7/0.860 = 0.814` — **28% off**. It was only *accidentally* correct at x=0.5 (with y constant, where `1/(2h) = 0.5/h` happens to hold) — exactly the point a casual spot-check would use.

Fix: `hypot` is split from `sqrt` in `inst_cache` (its cache now holds `hypot(x,y)` itself, not `2·hypot`), and its chain rule computes `(x·x' + y·y')/hypot` with the codebase's usual zero/one-derivative folding.

## `atan2(x,y)` — two bugs (magnitude and sign)

`atan2` shares the `Pow|Atan2` chain rule `(x'·c₀ + y'·c₁)·c₂`, but both cached factors were wrong:

1. the common factor `c₂` was set to `(x²+y²)` — but the shared rule **multiplies** by `c₂`, so it needed the **reciprocal** `1/(x²+y²)`;
2. the second-argument factor `c₁` was `+x`, but `d/du atan2(x,y) = (x'·y − y'·x)/(x²+y²)` **subtracts** the second term, so it needed `−x`.

The result was wrong in magnitude *and* sign: `atan2(V,0.5)` gave `0.5·0.74 = 0.37` (should be `0.5/0.74 = 0.676`), and `atan2(0.5,V)` gave `+0.37` where the answer is `−0.676`. Fix: `c₂ = 1/(x²+y²)`, `c₁ = −x`.

## Why it matters

`hypot` and `atan2` are used in real compact models — `hypot` for smoothed `√(x²+ε²)` turn-ons and velocity-saturation limiting, `atan2` for phase and geometry. A model using either compiled to a **correct DC bias but a silently wrong AC response, small-signal gain, noise, and Newton Jacobian**. Because the fix is at the autodiff-rule level it applies everywhere the derivative is taken — resistive currents, reactive charges (verified via AC susceptance of a `ddt(hypot…)`), higher-order derivatives, and `ddx`.

## Verification

[`examples/vafautodiff_examples/verify_vafautodiff.py`](../examples/vafautodiff_examples/verify_vafautodiff.py) — 9 checks: `hypot` d/dV in both argument orders equals `V/hypot`, equals the hand-expanded `sqrt(V²+0.25)` derivative, and is undisturbed at the V=0.5 accidental-correctness point; `atan2` d/dV matches `x/(x²+y²)` and `−y/(x²+y²)` (magnitude and sign) and `atan2(V,V)`→0; the fix reaches a reactive charge via AC susceptance; and a regression battery of 15 other math builtins (sin/cos/tan, the inverse and hyperbolic families, exp/ln/log/sqrt, pow) confirms their derivatives were already correct and stay correct. A compiler property, identical under both linear solvers, so it runs once. Full example regression: 150/150.
