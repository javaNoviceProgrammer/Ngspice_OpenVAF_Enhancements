# vafsqrtguard_examples — Enhancement-261

`sqrt()` derivative guard in openvaf-r's automatic differentiation.

## The bug

A Verilog-A conductor `I = K*sqrt(V)` has an infinite small-signal conductance
`dI/dV = K/(2·sqrt(V))` at ngspice's default `V = 0` initial guess. openvaf-r
emitted that raw `+inf`, which NaN-poisoned the Jacobian and made the DC
operating point **fail outright** — dynamic/true gmin, source, and
pseudo-transient stepping all died and the node returned `nan`. The
mathematically identical `pow(V,0.5)` converged, because `Pow` had a `base==0`
derivative guard that `sqrt` did not — a plain internal inconsistency in the
compiler.

## The fix

The emitted `sqrt` derivative is regularized to `K/(2·sqrt(V + a))` with
`a = 1e-18` — the exact derivative of the smoothly regularized `sqrt(V+a)`:

- **finite at `V = 0`** (`K/(2·sqrt(a))`, a large but bounded conductance), so
  the solver takes small controlled Newton steps and creeps out of the
  singularity to the true operating point — exactly like ngspice's own
  B-source `sqrt()`;
- **exact for `V > 0`** — because the nudge is *inside* the root, the
  perturbation is `~a/(2V)`, below the ULP, so no finite-bias derivative
  changes (higher-order derivatives and the `sqrt(1-x²)` inside
  `asin`/`acos`/… included);
- **composable** — being a plain value it propagates through downstream
  operators (`K*sqrt`, `1/(1+sqrt)`, `exp(-sqrt)`), which a block-split guard
  cannot.

## Files

- `sqrtguard_demo.va` — `sqrtdev` (`I = K*sqrt(V)`) and `sqrtcompose`
  (`I = G0/(1+sqrt(V))`).
- `verify_vafsqrtguard.py` — compiles the models with the committed `openvaf-r`
  and checks, under **both** linear solvers, that: bare and strongly-scaled
  `sqrt` find their true KCL operating point (not `nan`) and match the
  equivalent B-source; the guarded derivative is exact for `V > 0`; the
  composed `1/(1+sqrt)` converges; and `pow(V,0.5)` now agrees with `sqrt(V)`.

Run:

```
python3 verify_vafsqrtguard.py
```

Generated `_*.cir` / `*.osdi` artifacts are temporary (gitignored).
