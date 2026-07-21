# Enhancement-261 — openvaf-r: guard the `sqrt()` derivative singularity

A correctness/robustness fix in openvaf-r's automatic differentiation
(`openvaf/mir_autodiff/src/builder.rs`). A Verilog-A conductor `I = K*sqrt(V)`
failed to find **any** DC operating point; the mathematically identical
`pow(V,0.5)` did not — an internal inconsistency in the compiler.

## The bug

`d/dx sqrt(x) = 1/(2·sqrt(x))` is `+∞` at ngspice's default `x = 0` initial
guess. openvaf-r emitted that raw `+inf` into the Jacobian, which produced a
`nan` and made the operating point fail outright — dynamic/true gmin, source,
and pseudo-transient stepping all died and the node came back `nan`.

The tell was an internal inconsistency. `Pow` carried an explicit `base==0 →
derivative:=0` guard (added "to ensure numerical stability"); **`Sqrt` had
none**. So `sqrt(V)` NaN-failed while the identical `pow(V,0.5)` and `V**0.5`
converged, and ngspice's own behavioral `B`-source `sqrt(v(n))` converged too
(it has simulator-side singular-derivative guards). Same mathematics, three
different outcomes.

The `Pow` guard was also **incomplete**: it wraps the derivative in a block
split, so it only protects a *bare terminal* `pow`/`sqrt`. `2.0*pow(V,0.5)`
fails on the unmodified compiler because the downstream multiply consumes the
raw (unguarded) derivative.

## The fix

The `Sqrt` derivative cache is changed from `2·sqrt(x)` to **`2·sqrt(x + a)`**
(`a = 1e-18`) — the exact derivative of the smoothly regularized `sqrt(x+a)`,
so the emitted derivative becomes `x'/(2·sqrt(x + a))`:

- **finite at `x = 0`** — `1/(2·sqrt(a)) ≈ 5·10⁸`, a large but bounded
  conductance, so Newton takes small controlled steps and creeps out of the
  singularity to the true root, exactly like the B-source;
- **exact for `x > 0`** — because the nudge is *inside* the root, the
  perturbation is `~a/(2x)`, below the ULP. No finite-bias derivative changes,
  including higher-order derivatives and the internal `sqrt(1-x²)` of
  `asin`/`acos`/`asinh`/`acosh`/`atanh`;
- **composable** — being a plain value it propagates correctly through
  downstream operators (`K*sqrt(x)`, `1/(1+sqrt(x))`, `exp(-sqrt(x))`), which
  the block-split guard could not.

Two alternatives were rejected: a block-split `Sqrt` arm mirroring `Pow` (does
not compose — scaled `sqrt` still fails); and an additive `2·sqrt(x)+δ`
denominator (perturbs the derivative by `~δ/(2·sqrt(x)) ≈ 1e-9`, breaking the
bit-exact higher-order `asin`/`acos` autodiff unit tests). The
`sqrt(x + a)` form is exact to the ULP *and* convergent, so no test tolerance
was loosened.

`pow(x, fractional)` is unchanged: its base-derivative `(y/x)·xʸ` is an
`inf·0` form in the shared `Pow`/`Atan2` chain rule with no clean branchless
regularization, so it keeps its existing bare-only guard. `sqrt()` is the
standard spelling for a square root in compact models.

## Verification

`examples/vafsqrtguard_examples/verify_vafsqrtguard.py` (both solvers): bare and
strongly-scaled `K*sqrt(V)` (K = 1, 2, 5) find their true KCL operating point —
not `nan` — and match the equivalent B-source to ~1e-5; the guarded derivative
`K/(2·sqrt(V))` is exact for `V > 0` (~1e-6); the composed `G0/(1+sqrt(V))`
converges; and `pow(V,0.5)` now agrees with `sqrt(V)`. openvaf-r's own autodiff
test suite (including the numeric third-order `asin`/`acos` exactness checks at
`10·ε` tolerance) and the OSDI/`sim_back` MIR snapshots pass unchanged in value.
Full dual-solver example regression passes.
