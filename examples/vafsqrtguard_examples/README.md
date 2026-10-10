# vafsqrtguard_examples — Enhancements 261, 262 and 839

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

## Enhancement-839: only the singular point

The "below the ULP" above was wrong. The shift moved the derivative by `a/(2V)` at every bias,
which is 5 % at `V = 1e-17`. Compact models in SI units take square roots of quantities that
small, and HiSIM-SOI's loaded gm came out 7.8 % low (F2 of the
[2026-10-10 robustness campaign](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md)).
E-262's `pow` and E-580's `hypot` and `atan2` guards shifted every argument the same way.

[E-839](../../enhancements_doc/Enhancement-839.md) replaces the singular value alone, with a
select: `x > 0 ? 2*sqrt(x) : 2*sqrt(a)`, and the like for the others. Every derivative away
from zero is the unguarded one, bit for bit, and zero keeps its finite value.

Section [8] uses `smallarg.va` to check `sqrt`, `hypot`, `pow(., 2)`, `pow(., 0.5)` and
`atan2` of `s*V` with `s = 1e-17`, and `sqrt` and `pow` at `1e-30`, each against its
closed-form conductance to 1e-12. Seven of those eight checks fail on the E-838 compiler; the
other is the compile.

## Files

- `sqrtguard_demo.va` — `sqrtdev` (`I = K*sqrt(V)`) and `sqrtcompose`
  (`I = G0/(1+sqrt(V))`).
- `smallarg.va` — `smallarg`, each operator of a tiny argument (E-839).
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
