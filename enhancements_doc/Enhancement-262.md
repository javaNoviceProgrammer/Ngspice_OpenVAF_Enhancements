# Enhancement-262 — openvaf-r: guard the `pow(x,y)` base-derivative singularity

The `pow` companion to [Enhancement-261](Enhancement-261.md) (which fixed the
same singularity for `sqrt`). A Verilog-A conductor `I = K*pow(V, Y)` with
`0 < Y < 1` failed to find a DC operating point whenever the term was scaled or
combined; the fix makes it converge like `sqrt`, and removes the last openvaf-r
autodiff singular-derivative gap.

## The bug

For `0 < Y < 1`, `d/dx pow(x,y) = y·x^(y-1)` is `+∞` at ngspice's default
`x = 0` initial guess — the same singularity as `sqrt` (indeed `pow(x,0.5)` *is*
`sqrt(x)`). In openvaf-r's automatic differentiation this term is built by the
chain rule shared by `Pow` and `Atan2`:

```
d(pow) = (x'·cache[0] + y'·cache[1])·cache[2],   cache[0]=y/x, cache[2]=x^y
```

so the base term is `x'·(y/x)·x^y`. At `x = 0` that is `+inf · 0 = NaN` (the
`y/x` factor is `+inf`, the `x^y` factor is `0`), which poisons the Jacobian and
makes the operating point fail outright.

`Pow` carried a partial guard — a block split that forced the derivative to `0`
when `base == 0` — which is why a **bare terminal** `pow(V,0.5)` converged. But
a block split cannot compose: the derivative of a downstream instruction
(`2*pow(V,0.5)`, `1/(1+pow(V,0.5))`) consumes the *raw* derivative computed
inside the conditional block, so any scaled or combined fractional `pow` still
NaN-failed on the unmodified compiler.

## The fix

The same regularization E-261 used for `sqrt`: cache the derivative of the
`a`-shifted `pow(x + a, y)` (`a = 1e-18`), while the value `res = x^y` is
unchanged. The `Pow` cache becomes

```
cache[0] = y/(x+a),   cache[1] = ln(x+a),   cache[2] = (x+a)^y
```

so the shared chain rule now yields

```
base term:     x'·y·(x+a)^(y-1)
exponent term: y'·ln(x+a)·(x+a)^y
```

- both are **finite at `x = 0`** (`y·a^(y-1)` is large but bounded — a
  controlled Newton step out of the singularity, exactly like the `sqrt`
  guard and ngspice's B-source);
- both are **exact for `x > 0`** — the nudge is inside the power, so the
  perturbation is `~a/x`, below the ULP;
- both are **plain values**, so they compose through downstream operators.

With a composing branchless guard in place, the old block-split `Pow` guard is
removed. `Atan2` — which shares the chain-rule *arm* but has its own cache — is
untouched and verified unchanged. The `y ≥ 1` case is a no-op (no singularity:
`(x+a)^(y-1) ≈ x^(y-1)` and both `→ 0` at `x=0`), and the solution-dependent
exponent term is now finite at `x=0` too (`ln(x+a)` instead of `ln(0) = -inf`).

## Verification

`examples/vafsqrtguard_examples/verify_vafsqrtguard.py` gains checks **[6]** and
**[7]** (both solvers): bare and strongly-scaled `K*pow(V, Y)` — `K = 1,2,5` at
`Y = 0.5, 0.3, 0.25` — find their true KCL operating point (not `nan`, where the
unmodified compiler NaN-failed the scaled/fractional cases), and the guarded
derivative `K·Y·V^(Y-1)` is exact for `V > 0` (~1e-6). openvaf-r's own autodiff
suite (including the `atan2` and higher-order derivative checks) and the
OSDI/`sim_back` MIR snapshots pass unchanged in value. Full dual-solver example
regression passes — the many production models that use `pow` (BSIM, PSP, …) are
bit-unchanged for `V > 0`.

## Scope

Completes the openvaf-r autodiff singular-derivative work: E-261 covers `sqrt`,
E-262 covers `pow(x, fractional)`, using the identical inside-the-argument
regularization. `ln(x)` and `1/x` are left as-is — their *value* (not just the
derivative) is `±inf` at `x = 0`, so no derivative guard makes a model that
evaluates them at `x = 0` well-posed; that is the model's responsibility.
