# Enhancement-305 — ngspice: worst-case distance / MPFP high-sigma (`wcd`)

The named remainder of the statistical suite. [Enhancement-150](Enhancement-150.md)'s
`highsigma` reaches the rare tail with **scaled-sigma** importance sampling — inflate every
Gaussian sigma, then reweight. That is *direction-free*, which is exactly what makes it
robust for an arbitrary failure condition, but it spends its samples in every direction at
once. Its own write-up names the complement it does not implement: *"unlike mean-shift
importance sampling or worst-case-distance search it needs no gradient, sensitivity, or
most-probable-failure-point."*

This adds that complement, and it pairs directly with the design centering of
[Enhancement-206](Enhancement-206.md).

## The method

Work in **standardised normal space**: every statistical parameter is mapped to N(0,1), so
the joint density is spherically symmetric and probability decreases monotonically with
`|u|`. Write the performance margin as `g(u) > 0` for pass. Then the most probable failing
point is the one on the boundary closest to the origin, and its distance

```
beta = min |u|   subject to   g(u) = 0
```

is the **worst-case distance**. Because the density is spherical, the first-order (FORM)
failure probability is simply

```
P_fail ~= Phi(-beta)
```

which is exactly the sigma number a designer quotes. The search is the classical
**Hasofer-Lind / Rackwitz-Fiessler** iteration

```
u_{k+1} = [ (grad_g . u_k - g(u_k)) / |grad_g|^2 ] grad_g
```

with a forward-difference gradient. Its cost is **bounded** — a handful of iterations, each
of `1 + ndim` simulations — rather than the `1e6`-`1e9` samples plain Monte Carlo needs
merely to *see* a 4.5-6 sigma event.

```
wcd -metric -1/i(v1) -max 1004.5 -analysis op
```
```
  wcd: 1 statistical dimension, analysis 'op', fail if (-1/i(v1)) > max
    nominal margin g(0) = +4.5  (passes at nominal)

    worst-case distance : beta = 4.5000 sigma
    P(fail), first-order: 3.397673e-06   (= Phi(-beta))
    MPFP (standardised normal coordinates):
      u0=+4.5000
```

## Mean-shift refinement

FORM is **exact** when `g` is linear in `u` (the boundary is a hyperplane and `beta` is its
distance from the origin) and approximate when it curves. `-is N` therefore refines it with
**mean-shift importance sampling** centred on the MPFP: draw from `N(u*, I)` and carry the
exact likelihood ratio `phi(z)/phi(z-u*)`, giving an unbiased nominal-probability estimate
whose variance is small precisely because the samples land where the failures are.

```
  failures seen       : 986 / 2000 (in the shifted sampling)
  P(fail), mean-shift : 3.352941e-06  +/- 1.69e-07  (relative error 5.0%)
  equivalent sigma    : 4.503
```

**986 failures out of 2000**, for an event plain Monte Carlo would not see once in a million
runs. The analytic answer is `Phi(-4.5) = 3.3977e-06`.

## Implementation

Two new sampling modes behind the existing single funnel for Gaussian draws
(`mc_sample_gauss()` in `maths/misc/randnumb.c`), so this composes with the machinery
already there rather than duplicating it:

* **`MC_MODE_WCD`** — the draws are not random at all: dimension `d` returns a *chosen*
  coordinate `u[d]`, so the deck becomes a plain function `g(u)` that can be evaluated
  anywhere. This is what makes both the search and its finite-difference gradients possible.
* **`MC_MODE_SHIFT`** — draw `z = u*[d] + N(0,1)` and accumulate
  `log w = -u*.z + |u*|^2/2` into the same weight accumulator SSS already uses.

The **dimensionality is discovered, not declared**: how many Gaussian `.params` a deck draws
is unknown until it has been evaluated once, so `wcd` evaluates at the nominal point and asks
how many draws were consumed. The counter is a running maximum cleared once per evaluation,
because a single margin evaluation can trigger several deck-copy passes and a later pass that
draws nothing would otherwise wipe the count.

## Verification

`examples/wcd_examples/verify_wcd.py` — 19 checks under both solvers, every one against the
**analytic Gaussian tail** rather than a previous build. Since FORM is exact for a linear
margin, `R = 1000 + u` with a spec at `1000 + b` has the fully closed-form answer
`beta = b`, `P = Phi(-b)`:

| case | result |
|---|---|
| 1-D linear at 3 / 4 / 5 / 6 sigma | `beta` exact to machine precision; `P = Phi(-beta)` to ~1e-8 |
| lower (`-min`) spec | `beta = 4.5` exact |
| 2-D linear | dimensionality auto-discovered; MPFP on the symmetric point `(4/sqrt2, 4/sqrt2)` |
| nominal already failing | signed `beta = -3`, `P = Phi(+3)` |
| mean-shift IS | 3.353e-06 against the analytic 3.398e-06 |

The 2-D case is the load-bearing one: it is what shows the gradient search finds the right
**direction**, not merely a 1-D degenerate answer.

The four existing statistical suites (`highsigma`, `lhs`, `montecarlo`, `dcenter`) pass
unchanged — the new modes are only ever entered by this command.

## A deck-writing note

The statistical `.param` must reach a **device value** by brace substitution
(`R1 a 0 {rr}`), which is re-evaluated on every deck pass. Baked into a B-source
*expression* (`B1 out 0 v='rr'`) it is captured once and never varies; `wcd` then correctly
reports that the deck draws no Gaussian `.params` rather than silently searching a constant.

## Scope of change

`src/maths/misc/randnumb.c`, `src/include/ngspice/randnumb.h`, `src/frontend/com_sweep.c`,
`src/frontend/commands.c`.
