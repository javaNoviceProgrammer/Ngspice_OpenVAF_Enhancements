# Enhancement-187 — openvaf-r math-identity simplifier: invalid function-inverse cancellations

Continuing the deep audit of the openvaf-r compiler after the autodiff fixes ([E-185](Enhancement-185.md)/[186](Enhancement-186.md)), this one moves off the derivative path and onto the **algebraic simplifier** (`mir_opt/src/simplify.rs`) — the pass that rewrites `f(g(x)) → x` for function-inverse pairs to avoid redundant work. Six of those cancellations were **unconditionally wrong for ordinary finite inputs**, corrupting the **DC operating point itself** (not just a derivative — a strictly more severe class than the autodiff bugs).

## The defect

A cancellation `f(g(x)) = x` is valid only when `f` is a true **left inverse** of `g` over **all of g's range**. The simplifier applied it for every inverse pair, including compositions whose outer function only returns **principal values**:

| rewrite (was `→ x`) | correct result | wrong whenever |
|---|---|---|
| `asin(sin(x))` | principal angle in [−π/2, π/2] | \|x\| > π/2  (`asin(sin 3) = π−3 = 0.1416`) |
| `acos(cos(x))` | principal angle in [0, π] | x ∉ [0, π]  (`acos(cos 4) = 2π−4 = 2.283`) |
| `atan(tan(x))` | wrapped angle in (−π/2, π/2) | \|x\| > π/2  (`atan(tan 2) = 2−π = −1.142`) |
| `acosh(cosh(x))` | \|x\| (cosh is even) | x < 0  (`acosh(cosh −2) = 2`) |
| `sqrt(x*x)`, `sqrt(x**2)` | \|x\| | x < 0  (`sqrt((−3)²) = 3`, returned −3) |

`atan(tan(x))` is a **legitimate angle-wrapping idiom** — a model that writes it *wants* the sawtooth folding into (−π/2, π/2); collapsing it to `x` silently deletes the wrap. The `sqrt(x²) → x` rewrites are the classic “`√(x²)` is `|x|`, not `x`” mistake.

Crucially the constant-folding path (`eval_unary`) evaluates each operator numerically and was always correct, so a spot check on literal arguments passes — the bug lived only in the **symbolic** cancellation on runtime, bias-dependent values, exactly where DC-value tests on constants can’t see it.

## The fix

The four principal-value cancellations and both `sqrt(x²)` rewrites are removed (`Asin`/`Acos`/`Atan`/`Acosh` and `Sqrt` now decline to simplify). MIR has no `fabs` opcode to fold `sqrt(x²)` to, so the `sqrt` simply stays in place and computes `|x|` correctly. The cancellations that invert over the **whole real line** are kept and regression-checked — `tan(atan)`, `ln(exp)`, `asinh(sinh)`, `atanh(tanh)`, `sinh(asinh)`, `cosh(acosh)`, `log10(pow(10,·))`.

Rewrites that are unsound only for **Inf/NaN** inputs (`x−x → 0`, `x*0 → 0`, `sin(asin(x))`, `exp(ln(x))`, …) are standard finite-math behavior — Verilog-A models operate on finite quantities — and were deliberately left in place; the boundary drawn is “wrong for a finite, in-range input” = fix, “wrong only for Inf/NaN” = keep.

## Why it matters

`asin`/`acos`/`atan` and `sqrt(x²)`-as-`abs` appear in real behavioral models — angle geometry, phase wrapping, magnitude/rectification. Any such term compiled to a **silently wrong operating point, AC response, and Jacobian** on part of its input range, with no diagnostic. Because the rewrite is purely value-level, the wrong number propagated into every downstream analysis.

## Verification

[`examples/mathident_examples/verify_mathident.py`](../examples/mathident_examples/verify_mathident.py) — 12 DC-value checks: each formerly-buggy law compiled to OSDI, node biased, current read back (the wrong cancellation shows directly as a wrong current); the still-valid cancellations confirmed correct; and `sqrt` of a positive argument unaffected. [`wrap_demo.va`/`.cir`](../examples/mathident_examples/) sweep `atan(tan(V))` to draw the preserved sawtooth. The compiler’s own `mir_opt`/`mir`/`mir_autodiff` unit tests (13/19/7) are unchanged and pass. A compiler property, identical under both linear solvers, so the suite runs once. Full example regression: 151/151.
