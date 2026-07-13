# Enhancement-186 — openvaf-r autodiff audit: real-modulo (`%`) derivative fix

Continuing the deep audit of the openvaf-r compiler's **automatic differentiation** ([E-185](Enhancement-185.md)) — the pass (`mir_autodiff`) that builds the small-signal Jacobian used by AC analysis, Newton convergence, noise, pole-zero, and every derivative-dependent result. The same AC-conductance referee that caught the `hypot` and `atan2` derivative bugs (compare `g = dI/dV` of a nonlinear law `I = f(V)` against the *analytic* `f'(V)`) caught a third: **real modulo `%`** had its derivative forced to zero. It is the sixth occurrence of the accidental-correctness pattern this project keeps finding ([E-171](Enhancement-171.md)/[175](Enhancement-175.md)/[177](Enhancement-177.md)/[178](Enhancement-178.md)/[179](Enhancement-179.md)/[185](Enhancement-185.md)), and the second on the compiler side.

## `x % c` — derivative silently zero

Verilog-A real modulo lowers to the `Frem` opcode. Mathematically

```
x % c = x − floor(x/c)·c
```

is a slope-1 sawtooth in `x`: within each period the fractional remainder rises with `x`, so **`d/dx (x % c) = 1`** everywhere except the discrete wrap points (where `floor` jumps and the value is discontinuous anyway). Yet `Frem` was grouped with the genuinely-constant opcodes — `floor`, `ceil`, `$clog2`, the integer/bitwise ops, comparisons — and treated as having **derivative 0**, in *two* places that both had to be fixed:

1. **the live-derivative gate** (`mir_autodiff/src/lib.rs`, `zero_derivative`) — this decides which SSA values even *depend* on the differentiation variable. With `Frem` listed here, a modulo result was declared independent of the unknown, so the downstream current was considered constant and its derivative was **never requested**;
2. **the chain rule** (`mir_autodiff/src/builder.rs`, `inst_derivative`) — the `=> return` arm that emits no derivative edge.

Because the gate came first, the AC/Jacobian contribution of any modulo-dependent term was **identically zero** — a model computed the right DC value (`V % c` tracks `V` with slope 1) but contributed nothing to the small-signal conductance or the Newton Jacobian. The classic accidental-correctness signature: a `.dc` sweep of `I = 1e-3·(V % 1.0)` has slope exactly `1e-3`, while the AC conductance read `0`.

## The fix

`Frem` is removed from the zero-derivative group in both `lib.rs` and `builder.rs`, and given the correct rule

```
d/du (x % c) = x' − floor(x/c)·c'
```

For the overwhelmingly common **constant divisor** (`c' = 0`) this folds to just the dividend's derivative `x'` (slope 1, scaled by the outer chain). The general **bias-dependent divisor** term `−floor(x/c)·c'` is emitted only when the divisor actually carries a derivative. `floor(x/c)` is itself locally constant, so it contributes no further derivative — matching the exact algebra. `floor`/`ceil`/`$clog2`/integer ops stay in the zero group, correctly.

## Why it matters

Real modulo appears in compact and behavioral models for **phase wrapping** (`phase % (2·π)`), periodic geometry, and sawtooth/relaxation constructs. Any such term compiled to a **correct DC bias but a silently missing AC response, small-signal gain, noise, and Newton Jacobian entry** — and, unlike a wrong *value*, a missing Jacobian entry can also slow or break convergence. Because the fix is at the autodiff-rule level it applies everywhere the derivative is taken — resistive currents, reactive charges, higher-order derivatives, and the explicit `ddx` operator.

## Verification

[`examples/vafautodiff_examples/verify_vafautodiff.py`](../examples/vafautodiff_examples/verify_vafautodiff.py) — the E-185 autodiff battery, extended with five real-modulo checks: `d/dV (V % 1.0) = 1` and `d/dV (V % 0.4) = 1` (two constant divisors), the derivative scales with the outer prefactor, the chain rule flows *through* the modulo (`d/dV (V%1)² = 2·(V%1)` = 1.4 at V=0.7), and `floor`/`ceil` stay at 0 (undisturbed). A separate 3-terminal probe confirms the bias-dependent-divisor branch (`d/dc (x % c) = −floor(x/c)`). Cross-checked independently via the `ddx` value path (which exposes the same autodiff result as a DC-readable value) and the compiler's own 19 `mir_autodiff` unit tests (unchanged, all pass). A compiler property, identical under both linear solvers, so the suite runs once. Full example regression: 150/150.
