# wcd_examples — Enhancement-305

**Worst-case distance / most-probable-failure-point high-sigma** — the named remainder
of the statistical suite.

[Enhancement-150](../../enhancements_doc/Enhancement-150.md)'s `highsigma` reaches the
rare tail by inflating every sigma and reweighting. That is *direction-free* — robust for
an arbitrary failure condition — but it spends its samples in every direction at once.
`wcd` is the industry-standard complement: it works in **standardised normal space**
(each statistical parameter mapped to N(0,1)) and asks a geometric question instead.

With the performance margin written as `g(u) > 0` for pass, the most probable failing
point is the one on the boundary `g(u) = 0` closest to the origin. Its distance

```
beta = min |u|   subject to   g(u) = 0
```

is the **worst-case distance**, and because the density is spherically symmetric the
first-order (FORM) failure probability is `P_fail = Phi(-beta)` — exactly the sigma number
a designer quotes.

```
wcd -metric -1/i(v1) -max 1004.5 -analysis op
```
```
  worst-case distance : beta = 4.5000 sigma
  P(fail), first-order: 3.397673e-06   (= Phi(-beta))
  MPFP (standardised normal coordinates):
    u0=+4.5000
```

## Why it is cheap

The search is the classical Hasofer-Lind / Rackwitz-Fiessler iteration, whose cost is
**bounded**: a handful of iterations, each of `1 + ndim` simulations for the
finite-difference gradient — instead of the `1e6`-`1e9` samples plain Monte Carlo needs
merely to *see* a 4.5-6 sigma event.

## Mean-shift refinement

FORM is exact when `g` is linear in `u` and approximate when the boundary curves, so
`-is N` refines it by **mean-shift importance sampling** centred on the MPFP: sampling
`N(u*, I)` and carrying the likelihood ratio gives an unbiased estimate whose variance is
small precisely because the samples land where the failures are.

```
wcd -metric -1/i(v1) -max 1004.5 -analysis op -is 2000 -seed 1
```
```
  failures seen       : 986 / 2000 (in the shifted sampling)
  P(fail), mean-shift : 3.352941e-06  +/- 1.69e-07  (relative error 5.0%)
  equivalent sigma    : 4.503
```

**986 failures out of 2000** — for an event plain Monte Carlo would not see once in a
million runs. The analytic answer is 3.3977e-06.

## What the verification proves

FORM is **exact** for a linear margin, so these are checked against closed form, not
against a previous build:

| case | checked |
|---|---|
| 1-D linear, 3 / 4 / 5 / 6 sigma | `beta` exact; `P = Phi(-beta)` to ~1e-8 |
| lower (`-min`) spec | `beta = 4.5` |
| 2-D linear | dimensionality auto-discovered; MPFP on the symmetric point `u = (4/sqrt2, 4/sqrt2)` |
| nominal already failing | signed `beta = -3`, `P = Phi(+3)` |
| mean-shift IS | agrees with `Phi(-4.5)` |

The 2-D case is the one that matters most: it is what shows the gradient search finds the
right **direction**, not merely a 1-D degenerate answer.

## A note on writing the deck

The statistical `.param` must reach a **device value** by brace substitution
(`R1 a 0 {rr}`), which is re-evaluated on every deck pass. Baking it into a B-source
*expression* (`B1 out 0 v='rr'`) captures it once, so the parameter never varies and
`wcd` correctly reports that the deck draws no Gaussian `.params`.

## Verify

```bash
python3 verify_wcd.py
```

Runs under both linear solvers (19 checks), all against the analytic Gaussian tail.
