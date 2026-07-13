# openvaf-r math-identity simplifier audit (Enhancement-187)

The compiler's algebraic simplifier (`mir_opt/src/simplify.rs`) cancels
function-inverse pairs symbolically — `f(g(x)) → x` — to avoid redundant work.
A cancellation `f(g(x)) = x` is only valid when **f is a true left inverse of g
over all of g's range**. Several cancellations were applied *unconditionally*
even though the outer function only returns **principal values**, so they
produced the **wrong value** — the DC operating point itself, not merely a
derivative — for perfectly ordinary finite inputs.

## The bugs

| pattern (was → x) | correct result | wrong for |
|---|---|---|
| `asin(sin(x))` | principal angle in [−π/2, π/2] | \|x\| > π/2 — `asin(sin 3) = π−3 = 0.1416` |
| `acos(cos(x))` | principal angle in [0, π] | x ∉ [0, π] — `acos(cos 4) = 2π−4 = 2.283` |
| `atan(tan(x))` | wrapped angle in (−π/2, π/2) | \|x\| > π/2 — a **legitimate angle-wrap idiom** the optimizer silently defeated |
| `acosh(cosh(x))` | \|x\| (cosh is even) | x < 0 — `acosh(cosh −2) = 2` |
| `sqrt(x*x)`, `sqrt(x**2)` | \|x\| | x < 0 — `sqrt((−3)²) = 3`, not −3 |

The const-fold path evaluated each op correctly, so a spot check on constants
would pass — the bug was the *symbolic* cancellation on runtime, bias-dependent
values. Because it corrupts the value (not just the Jacobian), it is more severe
than the autodiff bugs of [Enhancement-185](../../enhancements_doc/Enhancement-185.md)/[186](../../enhancements_doc/Enhancement-186.md).

## The fix

The four principal-value cancellations and the two `sqrt(x²)` rewrites are
removed; MIR has no `fabs` to fold to, so the `sqrt` simply stays in place (it
computes `|x|` correctly). The cancellations that **are** valid over the whole
real line are kept — `tan(atan)`, `ln(exp)`, `asinh(sinh)`, `atanh(tanh)`,
`sinh(asinh)`, `cosh(acosh)`, `log10(pow(10,·))` — and regression-checked so the
fix did not over-reach. (Rewrites that are only unsound for Inf/NaN inputs, like
`x−x→0` or `sin(asin(x))`, are standard finite-math behavior and were left as-is.)

## Verification

`verify_mathident.py` — 12 checks: each formerly-buggy law compiled to OSDI,
biased, and read back via DC (the wrong cancellation shows as a wrong current);
plus the still-valid cancellations confirmed correct and `sqrt` of a positive
argument unaffected. A compiler property, identical under both linear solvers,
so it runs once.

`wrap_demo.va` / `wrap_demo.cir` sweep `atan(tan(V))` from −5 to 5 rad and draw
the characteristic sawtooth (jumps of π) that proves the wrap is preserved.

## Running

```sh
python3 verify_mathident.py
openvaf-r wrap_demo.va -o wrap_demo.osdi && ngspice -b wrap_demo.cir
```
